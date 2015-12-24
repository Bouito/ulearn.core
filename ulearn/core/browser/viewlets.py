from five import grok
from hashlib import sha1
from plone import api
from zope.interface import Interface
from plone.app.layout.viewlets.interfaces import IPortalHeader

from genweb.core.gwuuid import IGWUUID
from ulearn.core.content.community import ICommunity
from ulearn.core import _

import json


class CommunityNGDirective(grok.Viewlet):
    grok.context(ICommunity)
    grok.name('ulearn.communityngdirective')
    grok.viewletmanager(IPortalHeader)

    def update(self):
        self.community_hash = sha1(self.context.absolute_url()).hexdigest()
        self.community_gwuuid = IGWUUID(self.context).get()
        self.community_url = self.context.absolute_url()
        self.community_type = self.context.community_type


class ULearnNGDirectives(grok.Viewlet):
    grok.context(Interface)
    grok.name('ulearn.ulearnngdirectives')
    grok.viewletmanager(IPortalHeader)

    def get_communities(self):
        """ Gets the communities to show in the stats selectize dropdown
        """
        pc = api.portal.get_tool('portal_catalog')
        all_communities = [{'hash': 'all', 'title': _(u'Todas las comunidades')}]
        all_communities += [{'hash': community.community_hash, 'title': community.Title} for community in pc.searchResults(portal_type='ulearn.community')]
        return json.dumps(all_communities)

    def show_extended(self):
        """ This attribute from the directive is used to show special buttons or
            links in the stats tabs. This is common in client packages.
        """
        pqi = api.portal.get_tool('portal_quickinstaller')
        pid = 'ulearn.generali'
        installed = [p['id'] for p in pqi.listInstalledProducts()]
        return pid in installed
