#
# This file is part of Deluge and is licensed under GNU General Public License 3.0, or later, with
# the additional special exception to link portions of this program with the OpenSSL library.
# See LICENSE for more details.
#

from deluge.core.torrent import Torrent


class MockRPCServer:
    def __init__(self, session_id='session-1'):
        self.session_id = session_id

    def get_session_id(self):
        return self.session_id


def build_torrent(status):
    torrent = Torrent.__new__(Torrent)
    torrent.prev_status = {}
    torrent.rpcserver = MockRPCServer()
    torrent.status_funcs = {key: (lambda value=value: value) for key, value in status.items()}
    return torrent


def test_get_status_returns_full_payload_when_requested_keyset_expands():
    torrent = build_torrent(
        {
            'state': 'Seeding',
            'progress': 100,
            'save_path': '/downloads',
        }
    )

    assert torrent.get_status(['state', 'progress'], diff=True) == {
        'state': 'Seeding',
        'progress': 100,
    }

    assert torrent.get_status(['state', 'progress', 'save_path'], diff=True) == {
        'state': 'Seeding',
        'progress': 100,
        'save_path': '/downloads',
    }


def test_get_status_does_not_shrink_diff_baseline_after_narrower_request():
    torrent = build_torrent(
        {
            'state': 'Seeding',
            'progress': 100,
            'save_path': '/downloads',
        }
    )
    expected_status = {
        'state': 'Seeding',
        'progress': 100,
        'save_path': '/downloads',
    }

    assert torrent.get_status(['state', 'progress', 'save_path'], diff=True) == expected_status
    assert torrent.get_status(['state', 'progress'], diff=True) == {}
    assert torrent.get_status(['state', 'progress', 'save_path'], diff=True) == {}
    assert torrent.prev_status['session-1'] == expected_status
