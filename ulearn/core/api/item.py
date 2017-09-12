# -*- coding: utf-8 -*-
from five import grok
import requests
from Products.CMFPlone.interfaces import IPloneSiteRoot
from ulearn.core.api import ApiResponse
from ulearn.core.api import REST
from ulearn.core.api import api_resource
from ulearn.core.api.root import APIRoot
from plone import api
from base64 import b64encode


class Item(REST):
    """
        /api/item

        http://localhost:8090/Plone/api/item/?url=BITLY_URL

    """

    grok.adapts(APIRoot, IPloneSiteRoot)
    grok.require('genweb.authenticated')

    @api_resource(required=['url'])
    def GET(self):
        """ Expanded bitly links """
        url = self.params['url']
        session = requests.Session()
        resp = session.head(url, allow_redirects=True)
        if 'came_from' in resp.url:
            expanded = resp.url.split('came_from=')[1].replace('%3A', ':')
        else:
            expanded = resp.url

        #expanded = 'http://localhost:8090/Plone/news/noticia-2'
        #expanded = 'http://localhost:8090/Plone/download.png'
        expanded = 'http://localhost:8090/Plone/documento'

        portal = api.portal.get()
        local_url = portal.absolute_url()
        results = []
        if local_url in expanded:
            item_id = expanded.split(local_url)[1][1:]
            item_path = api.portal.getSite().absolute_url_path() + '/' + item_id
            value = api.content.find(path=item_path)[0]
            item = value.getObject()
            text = image = image_caption = ''
            raw_image = content_type = ''

            if value.portal_type == 'News Item':
                text = item.text.output
                image_caption = item.image_caption
                image = item.image.filename
            if value.portal_type == 'Image':
                image = item.image.filename
                raw_image = b64encode(item.image.data),
                content_type = item.image.contentType
            new = dict(title=value.Title,
                       id=value.id,
                       description=value.Description,
                       portal_type=value.portal_type,
                       external_url=False,
                       absolute_url=expanded,
                       text=text,
                       image_caption=image_caption,
                       image=image,
                       raw_image=raw_image,
                       content_type=content_type
                       )
            results.append(new)
        else:
            # Bit.ly object linked is from outside this Community
            # Only reports url
            value = api.content.find(path=local_url)
            new = dict(title='',
                       id='',
                       description='',
                       portal_type='',
                       external_url=True,
                       absolute_url=expanded,
                       text='',
                       image_caption='',
                       image='',
                       raw_image='',
                       content_type=''
                       )
            results.append(new)

        return ApiResponse(results)