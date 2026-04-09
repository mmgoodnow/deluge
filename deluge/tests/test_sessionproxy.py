#
# Copyright (C) 2016 bendikro <bro.devel+deluge@gmail.com>
#
# This file is part of Deluge and is licensed under GNU General Public License 3.0, or later, with
# the additional special exception to link portions of this program with the OpenSSL library.
# See LICENSE for more details.
#
from twisted.internet.defer import maybeDeferred, succeed
from twisted.internet.task import Clock

import deluge.component as component
import deluge.ui.sessionproxy
from deluge.conftest import BaseTestCase


class Core:
    def __init__(self):
        self.reset()

    def reset(self):
        self.torrents = {}
        self.torrents['a'] = {'key1': 1, 'key2': 2, 'key3': 3}
        self.torrents['b'] = {'key1': 1, 'key2': 2, 'key3': 3}
        self.torrents['c'] = {'key1': 1, 'key2': 2, 'key3': 3}
        self.current_session = 'sessionproxy'
        self.prev_status = {}

    def _get_requested_status(self, torrent_id, keys):
        if not keys:
            keys = list(self.torrents[torrent_id])
        return {key: self.torrents[torrent_id][key] for key in keys}

    def _get_torrent_ids(self, filter_dict):
        if not filter_dict:
            return list(self.torrents)

        if 'id' in filter_dict:
            return list(filter_dict['id'])

        torrent_ids = []
        for torrent_id, torrent in self.torrents.items():
            if all(
                (
                    torrent_id if field == 'hash' else torrent.get(field)
                )
                in values
                for field, values in filter_dict.items()
            ):
                torrent_ids.append(torrent_id)
        return torrent_ids

    def _get_diff_status(self, torrent_id, current_status):
        prev_status = self.prev_status.setdefault(self.current_session, {}).get(
            torrent_id
        )
        if prev_status is None:
            status = dict(current_status)
        else:
            status = {}
            for key, value in current_status.items():
                if key not in prev_status or prev_status[key] != value:
                    status[key] = value
        self.prev_status[self.current_session][torrent_id] = dict(current_status)
        return status

    def get_session_state(self):
        return maybeDeferred(self.torrents.keys)

    def get_torrent_status(self, torrent_id, keys, diff=False):
        current_status = self._get_requested_status(torrent_id, keys)
        if not diff:
            return succeed(current_status)

        return succeed(self._get_diff_status(torrent_id, current_status))

    def get_torrents_status(self, filter_dict, keys, diff=False):
        torrents = self._get_torrent_ids(filter_dict)
        ret = {}
        for torrent_id in torrents:
            current_status = self._get_requested_status(torrent_id, keys)
            if diff:
                ret[torrent_id] = self._get_diff_status(torrent_id, current_status)
            else:
                ret[torrent_id] = current_status
        return succeed(ret)


class Client:
    def __init__(self):
        self.core = Core()

    def __noop__(self, *args, **kwargs):
        return None

    def __getattr__(self, *args, **kwargs):
        return self.__noop__


client = Client()


class TestSessionProxy(BaseTestCase):
    def set_up(self):
        self.clock = Clock()
        self.patch(deluge.ui.sessionproxy, 'time', self.clock.seconds)
        self.patch(deluge.ui.sessionproxy, 'client', client)
        self.sp = deluge.ui.sessionproxy.SessionProxy()
        client.core.reset()
        d = self.sp.start()

        def do_get_torrents_status(torrent_ids):
            inital_keys = ['key1']
            # Advance clock to expire the cache times
            self.clock.advance(2)
            return self.sp.get_torrents_status({'id': torrent_ids}, inital_keys)

        d.addCallback(do_get_torrents_status)
        return d

    def tear_down(self):
        return component.deregister(self.sp)

    def test_startup(self):
        assert client.core.torrents['a'] == self.sp.torrents['a'][1]

    async def test_get_torrent_status_no_change(self):
        result = await self.sp.get_torrent_status('a', [])
        assert result == client.core.torrents['a']

    async def test_get_torrent_status_change_with_cache(self):
        client.core.torrents['a']['key1'] = 2
        result = await self.sp.get_torrent_status('a', ['key1'])
        assert result == {'key1': 1}

    async def test_get_torrent_status_change_without_cache(self):
        client.core.torrents['a']['key1'] = 2
        self.clock.advance(self.sp.cache_time + 0.1)
        result = await self.sp.get_torrent_status('a', [])
        assert result == client.core.torrents['a']

    async def test_get_torrent_status_key_not_updated(self):
        self.clock.advance(self.sp.cache_time + 0.1)
        self.sp.get_torrent_status('a', ['key1'])
        client.core.torrents['a']['key2'] = 99
        result = await self.sp.get_torrent_status('a', ['key2'])
        assert result == {'key2': 99}

    async def test_get_torrents_status_key_not_updated(self):
        self.clock.advance(self.sp.cache_time + 0.1)
        self.sp.get_torrents_status({'id': ['a']}, ['key1'])
        client.core.torrents['a']['key2'] = 99
        result = await self.sp.get_torrents_status({'id': ['a']}, ['key2'])
        assert result == {'a': {'key2': 99}}

    async def test_get_torrent_status_fetches_full_when_cache_missing_keys(self):
        client.core.torrents['a'] = {
            'hash': 'a',
            'state': 'Seeding',
            'progress': 100,
            'save_path': '/downloads',
            'label': 'linux',
        }
        expected_status = {
            'state': 'Seeding',
            'progress': 100,
            'save_path': '/downloads',
            'label': 'linux',
        }
        client.core.prev_status = {}
        self.sp.torrents['a'] = [self.clock.seconds() - self.sp.cache_time - 1, {}]
        self.sp.cache_times['a'] = {}

        result = await client.core.get_torrent_status('a', ['state', 'progress'], True)
        assert result == {'state': 'Seeding', 'progress': 100}

        result = await self.sp.get_torrent_status(
            'a', ['state', 'progress', 'save_path', 'label']
        )
        assert result == expected_status

    async def test_get_torrents_status_fetches_full_when_filtered_cache_missing_keys(
        self,
    ):
        client.core.torrents['a'] = {
            'hash': 'a',
            'state': 'Seeding',
            'progress': 100,
            'save_path': '/downloads',
            'label': 'linux',
        }
        expected_status = {
            'state': 'Seeding',
            'progress': 100,
            'save_path': '/downloads',
            'label': 'linux',
        }
        client.core.prev_status = {}
        self.sp.torrents['a'] = [self.clock.seconds() - self.sp.cache_time - 1, {}]
        self.sp.cache_times['a'] = {}

        result = await client.core.get_torrents_status(
            {'id': ['a']}, ['state', 'progress'], True
        )
        assert result == {'a': {'state': 'Seeding', 'progress': 100}}

        result = await self.sp.get_torrents_status(
            {'hash': 'a'}, ['state', 'progress', 'save_path', 'label']
        )
        assert result == {'a': expected_status}

    def test_on_torrent_state_changed_updates_cached_state(self):
        self.sp.torrents['a'][1]['state'] = 'Paused'

        self.sp.on_torrent_state_changed('a', 'Seeding')

        assert self.sp.torrents['a'][1]['state'] == 'Seeding'
