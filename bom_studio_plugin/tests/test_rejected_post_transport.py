"""Rejected local requests deliver an error without executing opaque bodies."""
from email.message import Message
import http.client
import json
import threading
import time
import unittest
from unittest.mock import Mock, patch

from bomstudio.server import Application, Handler, Server


class RejectedPostTransportTests(unittest.TestCase):
    def test_delayed_rejected_body_returns_json_and_never_dispatches(self):
        app = Application()
        server = Server(app)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            with patch.object(Handler, 'dispatch') as dispatch:
                for scenario in ('missing-token', 'wrong-origin', 'wrong-host'):
                    for _ in range(10):
                        body = b'{"opaque":"not executed"}'
                        connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
                        try:
                            connection.putrequest('POST', '/api/health/run', skip_host=True)
                            connection.putheader('Host', 'example.invalid' if scenario=='wrong-host' else f'127.0.0.1:{server.server_port}')
                            if scenario=='wrong-origin':connection.putheader('Origin', 'https://example.invalid')
                            connection.putheader('Content-Type', 'application/json')
                            connection.putheader('Content-Length', str(len(body)))
                            connection.endheaders()
                            time.sleep(.005)
                            connection.send(body)
                            response = connection.getresponse()
                            self.assertEqual(response.status, 401 if scenario=='missing-token' else 403)
                            self.assertIn('error', json.loads(response.read()))
                        finally:
                            connection.close()
                dispatch.assert_not_called()
        finally:
            server.shutdown();server.server_close();worker.join(3)

    def rejection(self, lengths, transfer=None):
        handler = object.__new__(Handler)
        handler.command = 'POST'
        handler.headers = Message()
        for length in lengths:handler.headers['Content-Length'] = length
        if transfer:handler.headers['Transfer-Encoding'] = transfer
        handler.connection = Mock()
        handler.connection.gettimeout.return_value = None
        handler.rfile = Mock()
        handler.rfile.read1.return_value = b'x'
        handler.respond = Mock()
        return handler

    def test_oversized_or_ambiguous_bodies_are_not_consumed(self):
        for lengths, transfer in ((['65537'],None),(['1','1'],None),(['1,1'],None),(['1'],'chunked'),([],None)):
            with self.subTest(lengths=lengths,transfer=transfer):
                handler = self.rejection(lengths,transfer)
                handler.reject('denied',401)
                handler.rfile.read1.assert_not_called()
                handler.respond.assert_called_once_with({'error':'denied'},401)
                self.assertTrue(handler.close_connection)

    def test_trickle_body_has_total_deadline_and_timeout_is_restored(self):
        handler = self.rejection(['100'])
        with patch('time.monotonic', side_effect=[0., .1, .2, .3]):
            handler.reject('denied',401)
        self.assertEqual(handler.rfile.read1.call_count,2)
        handler.connection.settimeout.assert_called_with(None)
        handler.respond.assert_called_once_with({'error':'denied'},401)


if __name__=='__main__':unittest.main()
