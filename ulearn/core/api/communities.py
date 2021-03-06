# -*- coding: utf-8 -*-
from five import grok
from hashlib import sha1

from Products.CMFPlone.utils import safe_unicode
from Products.CMFPlone.interfaces import IPloneSiteRoot
from plone import api
from zope.component import queryUtility
from plone.i18n.normalizer.interfaces import IIDNormalizer

from ulearn.core.api import ApiResponse
from ulearn.core.api import BadParameters
from ulearn.core.api import REST
from ulearn.core.api import api_resource
from ulearn.core.api import logger
from ulearn.core.api.root import APIRoot
from ulearn.core.content.community import ICommunityACL

from repoze.catalog.query import Eq
from souper.soup import get_soup
import requests
from plone.namedfile.file import NamedBlobImage
from mimetypes import MimeTypes
from base64 import b64encode


class CommunityMixin(object):
    """ """
    # Transferred to __init__
    # def lookup_community(self):
    #     pc = api.portal.get_tool(name='portal_catalog')
    #     result = pc.searchResults(community_hash=self.params['community'])
    #
    #     if not result:
    #         # Fallback search by gwuuid
    #         result = pc.searchResults(gwuuid=self.params['community'])
    #
    #         if not result:
    #             # Not found either by hash nor by gwuuid
    #             error_message = 'Community with has {} not found.'.format(self.params['community'])
    #             logger.error(error_message)
    #             raise ObjectNotFound(error_message)
    #
    #     self.community = result[0].getObject()
    #     return True


class CommunitiesGWOPA(REST):
    """
        /api/communitiesgwopa
    """

    placeholder_type = 'communitygwopa'
    placeholder_id = 'communitygwopa'

    grok.adapts(APIRoot, IPloneSiteRoot)
    grok.require('genweb.authenticated')

    @api_resource(required_roles=['Member', 'Manager'])
    def GET(self):
        """ Returns all the user communities and the open ones. """

        # Hard security validation as the view is soft checked
        # check_permission = self.check_roles(roles=['Member', 'Manager'])
        # if check_permission is not True:
        #     return check_permission

        # Get all communities for the current user
        pc = api.portal.get_tool('portal_catalog')
        r_results = pc.searchResults(portal_type='ulearn.community', community_type=[u'Closed', u'Organizative'])
        ur_results = pc.unrestrictedSearchResults(portal_type='ulearn.community', community_type=u'Open')
        communities = r_results + ur_results

        self.is_role_manager = False
        self.username = api.user.get_current().id
        global_roles = api.user.get_roles()
        if 'Manager' in global_roles:
            self.is_role_manager = True

        result = []
        favorites = self.get_favorites()
        for brain in communities:
            if brain.community_type == 'Closed':
                community_type = 'WOP Team'
            if brain.community_type == 'Open':
                community_type = 'Community of Practice'
            if brain.community_type == 'Organizative':
                community_type = 'Corporate'
            community = dict(id=brain.id,
                             title=brain.Title,
                             description=brain.Description,
                             url=brain.getURL(),
                             gwuuid=brain.gwuuid,
                             type=community_type,
                             image=brain.image_filename if brain.image_filename else False,
                             favorited=brain.id in favorites,
                             can_manage=self.is_community_manager(brain))
            result.append(community)

        return ApiResponse(result)

    def get_favorites(self):
        pc = api.portal.get_tool('portal_catalog')

        results = pc.unrestrictedSearchResults(favoritedBy=self.username)
        return [favorites.id for favorites in results]

    def is_community_manager(self, community):
        # The user has role Manager
        if self.is_role_manager:
            return True

        gwuuid = community.gwuuid
        portal = api.portal.get()
        soup = get_soup('communities_acl', portal)

        records = [r for r in soup.query(Eq('gwuuid', gwuuid))]
        if records:
            return self.username in [a['id'] for a in records[0].attrs['acl']['users'] if a['role'] == u'owner']


class CommunitiesMigration(REST):
    """
        /api/communitiesmigration
    """

    placeholder_type = 'community'
    placeholder_id = 'community'

    grok.adapts(APIRoot, IPloneSiteRoot)
    grok.require('genweb.authenticated')

    @api_resource(required_roles=['Manager'])
    def GET(self):
        """ Returns all communities """

        # Get all communities
        pc = api.portal.get_tool('portal_catalog')
        communities = pc.unrestrictedSearchResults(portal_type='ulearn.community')

        result = []
        for brain in communities:
            object_community = brain.getObject()
            try:
                community = dict(id=brain.id,
                                 title=brain.Title,
                                 description=brain.Description,
                                 url=brain.getURL(),
                                 gwuuid=brain.gwuuid,
                                 type=brain.community_type,
                                 image=brain.image_filename if brain.image_filename else False,
                                 listCreators=brain.listCreators,
                                 ModificationDate=brain.ModificationDate,
                                 CreationDate=brain.CreationDate,
                                 favoritedBy=str(brain.favoritedBy),
                                 community_hash=brain.community_hash,
                                 is_shared=brain.is_shared,
                                 Creator=brain.Creator,
                                 UID=brain.UID,
                                 editacl=self.get_editacl(brain),
                                 twitter_hashtag=object_community.twitter_hashtag,
                                 notify_activity_via_push=object_community.notify_activity_via_push,
                                 notify_activity_via_push_comments_too=object_community.notify_activity_via_push_comments_too,
                                 activity_view=object_community.activity_view,
                                 rawimage=b64encode(object_community.image.data) if object_community.image else ''
                                 )
                result.append(community)
            except:
                logger.info('HA FALLAT LA COMUNITAT {}'.format(brain.id))

        return ApiResponse(result)

    def get_editacl(self, community):
        # The user has role Manager

        gwuuid = community.gwuuid
        portal = api.portal.get()
        soup = get_soup('communities_acl', portal)

        records = [r for r in soup.query(Eq('gwuuid', gwuuid))]
        editacl = dict(users=records[0].attrs['acl'].get('users', ''),
                       groups=records[0].attrs['acl'].get('groups', ''))
        return editacl


class SaveEditACL(REST):
    """
        Simulate save on any communities on the Site.
        Used to update the LDAP groups users membership.
        Refresh users removed from LDAP in the soup catalog.

            /api/saveeditacl
    """

    placeholder_type = 'saveeditacl'
    placeholder_id = 'saveeditacl'

    grok.adapts(APIRoot, IPloneSiteRoot)
    grok.require('ulearn.APIAccess')

    @api_resource(required_roles=['Api'])
    def GET(self):
        """ Launch an editacl SAVE process on all communities """
        pc = api.portal.get_tool('portal_catalog')
        communities = pc.unrestrictedSearchResults(portal_type='ulearn.community')
        results = []
        communities_ok = []
        communities_error = []
        for item in communities:
            try:
                self.target = item._unrestrictedGetObject()
                self.payload = ICommunityACL(self.target)().attrs.get('acl', '')
                adapter = self.target.adapted(request=self.request)
                adapter.update_acl(self.payload)
                acl = adapter.get_acl()
                adapter.set_plone_permissions(acl)
                adapter.update_hub_subscriptions()
                updated = 'Updated community subscriptions on: "{}" '.format(self.target.absolute_url())
                logger.info(updated)
                communities_ok.append(self.target.absolute_url())
            except:
                error = 'Error updating community subscriptions on: "{}" '.format(self.target.absolute_url())
                logger.error(error)
                communities_error.append(self.target.absolute_url())

        results.append(dict(successfully_updated_communities=communities_ok,
                            error_updating_communities=communities_error))

        return ApiResponse(results)


class Communities(REST):
    """
        /api/communities
    """

    placeholder_type = 'community'
    placeholder_id = 'community'

    grok.adapts(APIRoot, IPloneSiteRoot)
    grok.require('genweb.authenticated')

    @api_resource(required_roles=['Member', 'Manager'])
    def GET(self):
        """ Returns all the user communities and the open ones. """

        # Hard security validation as the view is soft checked
        # check_permission = self.check_roles(roles=['Member', 'Manager'])
        # if check_permission is not True:
        #     return check_permission

        # Get all communities for the current user
        pc = api.portal.get_tool('portal_catalog')
        r_results = pc.searchResults(portal_type='ulearn.community', community_type=[u'Closed', u'Organizative'])
        ur_results = pc.unrestrictedSearchResults(portal_type='ulearn.community', community_type=u'Open')
        communities = r_results + ur_results

        self.is_role_manager = False
        self.username = api.user.get_current().id
        global_roles = api.user.get_roles()
        if 'Manager' in global_roles:
            self.is_role_manager = True

        result = []
        favorites = self.get_favorites()
        for brain in communities:
            community = dict(id=brain.id,
                             title=brain.Title,
                             description=brain.Description,
                             url=brain.getURL(),
                             gwuuid=brain.gwuuid,
                             type=brain.community_type,
                             image=brain.image_filename if brain.image_filename else False,
                             favorited=brain.id in favorites,
                             can_manage=self.is_community_manager(brain))
            result.append(community)

        return ApiResponse(result)

    @api_resource(required=['title', 'community_type'])
    def POST(self):
        params = {}
        params['nom'] = self.params.pop('title')
        params['community_type'] = self.params.pop('community_type')
        params['description'] = self.params.pop('description', None)
        params['image'] = self.params.pop('image', None)
        params['activity_view'] = self.params.pop('activity_view', None)
        params['twitter_hashtag'] = self.params.pop('twitter_hashtag', None)
        params['notify_activity_via_push'] = self.params.pop('notify_activity_via_push', None)
        params['notify_activity_via_push_comments_too'] = self.params.pop('notify_activity_via_push_comments_too', None)

        pc = api.portal.get_tool('portal_catalog')
        nom = safe_unicode(params['nom'])
        util = queryUtility(IIDNormalizer)
        id_normalized = util.normalize(nom, max_length=500)
        result = pc.unrestrictedSearchResults(portal_type='ulearn.community',
                                              id=id_normalized)

        imageObj = ''
        if params['image']:
            mime = MimeTypes()
            mime_type = mime.guess_type(params['image'])
            imgName = (params['image'].split('/')[-1]).decode('utf-8')
            imgData = requests.get(params['image']).content
            imageObj = NamedBlobImage(data=imgData,
                                      filename=imgName,
                                      contentType=mime_type[0])

        if result:
            # community = result[0].getObject()
            success_response = 'Community already exists.'
            status = 200
        else:
            new_community_id = self.context.invokeFactory('ulearn.community', id_normalized,
                                                          title=params['nom'],
                                                          description=params['description'],
                                                          image=imageObj,
                                                          community_type=params['community_type'],
                                                          activity_view=params['activity_view'],
                                                          twitter_hashtag=params['twitter_hashtag'],
                                                          notify_activity_via_push=True if params['notify_activity_via_push'] == 'True' else None,
                                                          notify_activity_via_push_comments_too=True if params['notify_activity_via_push_comments_too'] == 'True' else None,
                                                          checkConstraints=False)
            new_community = self.context[new_community_id]
            success_response = 'Created community "{}" with hash "{}".'.format(new_community.absolute_url(), sha1(new_community.absolute_url()).hexdigest())
            status = 201
        logger.info(success_response)
        return ApiResponse.from_string(success_response, code=status)

    def get_favorites(self):
        pc = api.portal.get_tool('portal_catalog')

        results = pc.unrestrictedSearchResults(favoritedBy=self.username)
        return [favorites.id for favorites in results]

    def is_community_manager(self, community):
        # The user has role Manager
        if self.is_role_manager:
            return True

        gwuuid = community.gwuuid
        portal = api.portal.get()
        soup = get_soup('communities_acl', portal)

        records = [r for r in soup.query(Eq('gwuuid', gwuuid))]
        if records:
            return self.username in [a['id'] for a in records[0].attrs['acl']['users'] if a['role'] == u'owner']


class Community(REST, CommunityMixin):
    """
        /api/communities/{community}
    """

    grok.adapts(Communities, IPloneSiteRoot)
    grok.require('genweb.authenticated')

    def __init__(self, context, request):
        super(Community, self).__init__(context, request)

    @api_resource(get_target=True, required_roles=['Owner', 'Manager'])
    def PUT(self):
        """ Modifies the community itself. """
        params = {}
        params['title'] = self.params.pop('title', None)
        params['community_type'] = self.params.pop('community_type', None)
        params['description'] = self.params.pop('description', None)
        params['image'] = self.params.pop('image', None)
        params['activity_view'] = self.params.pop('activity_view', None)
        params['twitter_hashtag'] = self.params.pop('twitter_hashtag', None)
        params['notify_activity_via_push'] = self.params.pop('notify_activity_via_push', None)
        params['notify_activity_via_push_comments_too'] = self.params.pop('notify_activity_via_push_comments_too', None)

        if params['community_type']:
            # We are changing the type of the community
            # Check if it's a legit change
            if params['community_type'] in ['Open', 'Closed', 'Organizative']:
                adapter = self.target.adapted(name=params['community_type'])
            else:
                return ApiResponse.from_string({"error": "Bad request, wrong community type"}, code=400)

            if params['community_type'] == self.target.community_type:
                return ApiResponse.from_string({"error": "Bad request, already that community type"}, code=400)

            # Everything is ok, proceed
            adapter.update_community_type()

        modified = self.update_community(params)
        if modified:
            success_response = 'Updated community "{}"'.format(self.target.absolute_url())
        else:
            success_response = 'Error with change values "{}".'.format(self.target.absolute_url())

        logger.info(success_response)
        return ApiResponse.from_string(success_response)

    @api_resource(get_target=True, required_roles=['Owner', 'Manager'])
    def DELETE(self):
        # Check if there's a valid community with the requested hash
        # lookedup_obj = self.lookup_community()
        # if lookedup_obj is not True:
        #     return lookedup_obj

        # Hard security validation as the view is soft checked
        # check_permission = self.check_roles(self.community, ['Owner', 'Manager'])
        # if check_permission is not True:
        #     return check_permission
        api.content.delete(obj=self.target)

        return ApiResponse({}, code=204)

    def update_community(self, properties):
        pc = api.portal.get_tool('portal_catalog')
        brain = pc.unrestrictedSearchResults(portal_type='ulearn.community',
                                             community_hash=self.params['community'])
        if not brain:
            brain = pc.unrestrictedSearchResults(portal_type='ulearn.community',
                                                 gwuuid=self.params['community'])
        if brain:
            community = brain[0].getObject()
            if properties['title'] is not None:
                community.title = properties['title']
            if properties['description'] is not None:
                community.description = properties['description']
            if properties['image'] is not None:
                imageObj = ''
                mime = MimeTypes()
                mime_type = mime.guess_type(properties['image'])
                imgName = (properties['image'].split('/')[-1]).decode('utf-8')
                imgData = requests.get(properties['image']).content
                imageObj = NamedBlobImage(data=imgData,
                                          filename=imgName,
                                          contentType=mime_type[0])
                community.image = imageObj
            if properties['activity_view'] is not None:
                community.activity_view = properties['activity_view']
            if properties['twitter_hashtag'] is not None:
                community.twitter_hashtag = properties['twitter_hashtag']
            if properties['notify_activity_via_push'] is not None:
                community.notify_activity_via_push = True if properties['notify_activity_via_push'] == 'True' else None
            if properties['notify_activity_via_push_comments_too'] is not None:
                community.notify_activity_via_push_comments_too = True if properties['notify_activity_via_push_comments_too'] == 'True' else None
            community.reindexObject()
            return True
        else:
            return False


class Count(REST, CommunityMixin):
    """
        /api/communities/count/{community_type}

        /api/communities/count?community_type=Closed
    """

    grok.adapts(Communities, IPloneSiteRoot)
    grok.require('genweb.authenticated')

    def __init__(self, context, request):
        super(Count, self).__init__(context, request)

    @api_resource()
    def GET(self):
        """ Return the number of communities. """
        pc = api.portal.get_tool('portal_catalog')
        community_type = self.params.pop('community_type', None)
        if community_type is not None:
            results = pc.unrestrictedSearchResults(portal_type='ulearn.community', community_type=community_type)
        else:
            results = pc.unrestrictedSearchResults(portal_type='ulearn.community')

        return ApiResponse(len(results))


class Subscriptions(REST, CommunityMixin):
    """
        /api/communities/{community}/subscriptions

        Manages the community subscriptions (ACL) for a given list of
        users/groups in the form:

        {'users': [{'id': 'user1', 'displayName': 'Display name', 'role': 'owner'}],
         'groups': [{'id': 'group1', 'displayName': 'Display name', 'role': 'writer'}]}

        At this time of writting (Feb2015), there are only three roles available
        and each other exclusive: owner, writer, reader.
    """

    grok.adapts(Community, IPloneSiteRoot)
    grok.require('genweb.authenticated')

    @api_resource(get_target=True, required_roles=['Owner', 'Manager'])
    def GET(self):
        """
            Get the subscriptions for the community. The security is given an
            initial soft check for authenticated users at the view level and
            then by checking explicitly if the requester user has permission on
            the target community.
        """
        # Lookup for object
        # lookedup_obj = self.lookup_community()
        # if lookedup_obj is not True:
        #     return lookedup_obj

        # Hard security validation as the view is soft checked
        # check_permission = self.check_roles(self.community, ['Owner', 'Manager'])
        # if check_permission is not True:
        #     return check_permission
        result = ICommunityACL(self.target)().attrs.get('acl', '')

        return ApiResponse(result)

    @api_resource(get_target=True, required_roles=['Owner', 'Manager'])
    def POST(self):
        """
            Subscribes a bunch of users to a community the security is given an
            initial soft check for authenticated users at the view level and
            then by checking explicitly if the requester user has permission on
            the target community.
        """
        # Lookup for object
        # lookedup_obj = self.lookup_community()
        # if lookedup_obj is not True:
        #     return lookedup_obj

        # Hard security validation as the view is soft checked
        # check_permission = self.check_roles(self.community, ['Owner', 'Manager'])
        # if check_permission is not True:
        #     return check_permission

        self.set_subscriptions()

        # Response successful
        success_response = 'Updated community "{}" subscriptions'.format(self.target.absolute_url())
        logger.info(success_response)
        return ApiResponse.from_string(success_response)

    @api_resource(get_target=True, required_roles=['Owner', 'Manager'])
    def PUT(self):
        """
            Subscribes a bunch of users to a community the security is given an
            initial soft check for authenticated users at the view level and
            then by checking explicitly if the requester user has permission on
            the target community.
        """

        self.update_subscriptions()

        # Response successful
        success_response = 'Updated community "{}" subscriptions'.format(self.target.absolute_url())
        logger.info(success_response)
        return ApiResponse.from_string(success_response)

    @api_resource(get_target=True, required_roles=['Owner', 'Manager'])
    def DELETE(self):
        # # Check if there's a valid community with the requested hash
        # lookedup_obj = self.lookup_community()
        # if lookedup_obj is not True:
        #     return lookedup_obj
        #
        # # Hard security validation as the view is soft checked
        # check_permission = self.check_roles(self.community, ['Owner', 'Manager'])
        # if check_permission is not True:
        #     return check_permission

        self.remove_subscriptions()

        # Response successful
        success_response = 'Unsubscription to the requested community done.'
        logger.info(success_response)
        return ApiResponse.from_string(success_response, code=200)

    def set_subscriptions(self):
        adapter = self.target.adapted(request=self.request)

        # Change the uLearn part of the community
        adapter.update_acl(self.payload)
        acl = adapter.get_acl()
        adapter.set_plone_permissions(acl)

        # Communicate the change in the community subscription to the uLearnHub
        # XXX: Until we do not have a proper Hub online
        adapter.update_hub_subscriptions()

    def update_subscriptions(self):
        adapter = self.target.adapted(request=self.request)

        # Change the uLearn part of the community

        users = self.params.pop('users')
        for user in users:
            try:
                adapter.update_acl_atomic(user['id'], user['role'])
            except:
                raise BadParameters(user)

        acl = adapter.get_acl()
        adapter.set_plone_permissions(acl)
        adapter.update_hub_subscriptions()

    def remove_subscriptions(self):
        adapter = self.target.adapted(request=self.request)

        users = self.params.pop('users')
        for user in users:
            try:
                adapter.remove_acl_atomic(user['id'])
            except:
                raise BadParameters(user)

        acl = adapter.get_acl()
        adapter.set_plone_permissions(acl)
        adapter.update_hub_subscriptions()
