# -*- coding: utf-8 -*-
import unittest2 as unittest
from hashlib import sha1
from plone import api
from AccessControl import Unauthorized
from zope.event import notify
from zope.lifecycleevent import ObjectAddedEvent
from zope.lifecycleevent import ObjectModifiedEvent
from zope.component import getUtility
from zope.component import getMultiAdapter
from zope.component import getAdapter

from plone.app.testing import login
from plone.app.testing import logout
from plone.app.testing import setRoles
from plone.app.testing import TEST_USER_ID

from Products.CMFCore.utils import getToolByName

from repoze.catalog.query import Eq
from souper.soup import get_soup
from souper.soup import Record

from genweb.core.gwuuid import IGWUUID

from mrs.max.utilities import IMAXClient
from ulearn.core.tests import uLearnTestBase
from ulearn.core.content.community import ICommunityTyped
from ulearn.core.testing import ULEARN_CORE_INTEGRATION_TESTING

import os


class TestExample(uLearnTestBase):

    layer = ULEARN_CORE_INTEGRATION_TESTING

    def setUp(self):
        self.app = self.layer['app']
        self.portal = self.layer['portal']
        self.request = self.layer['request']

        self.maxclient, settings = getUtility(IMAXClient)()
        self.username = settings.max_restricted_username
        self.token = settings.max_restricted_token

        self.maxclient.setActor(settings.max_restricted_username)
        self.maxclient.setToken(settings.max_restricted_token)

    @unittest.skipIf(os.environ.get('JENKINS', False), 'Skipping due to lack of LDAP access')
    def test_group_sync(self):
        sync_view = getMultiAdapter((self.portal, self.request), name='syncldapgroups')
        sync_view.render()

        soup = get_soup('ldap_groups', self.portal)

        self.assertTrue(len(soup.data.keys()) > 0)
