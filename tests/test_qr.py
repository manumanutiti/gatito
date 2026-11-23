"""gatito's own QR generator (gatitod/qr.py).

Known case: the matrix of a pairing URL, compared with the `qrcode` library
(if installed) in all 8 masks, and a fixed fingerprint that was checked
against it so the test still counts without the library.
"""
import hashlib
import unittest

import env_portability  # noqa: F401
import qr

URL = 'https://192.168.1.37:8777/?t=AbCdEfGhIjKlMnOpQrStUvWx'


def fingerprint(m):
    return hashlib.sha256(''.join('1' if c else '0' for f in m for c in f).encode()).hexdigest()[:16]


class TestQR(unittest.TestCase):
    def test_fingerprint_known(self):
        m = qr.matrix(URL, mascara=0)
        self.assertEqual(len(m), 33)   # version 4
        self.assertEqual(fingerprint(m), FINGERPRINT_URL_M0)

    def test_against_library_qrcode(self):
        try:
            import qrcode
            from qrcode.util import QRData, MODE_8BIT_BYTE
        except ImportError:
            self.skipTest('qrcode library not installed')
        for text in ('hello', URL, 'https://Anas-MacBook.local:8777/?t=' + 'x' * 24, 'é' * 30, 'a' * 150, 'q' * 210):
            for k in range(8):
                ref = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=0, mask_pattern=k)
                ref.add_data(QRData(text.encode(), mode=MODE_8BIT_BYTE))
                ref.make(fit=True)
                self.assertEqual(qr.matrix(text, mascara=k), ref.get_matrix(), (text[:20], k))

    def test_svg_and_limit(self):
        s = qr.svg(URL)
        self.assertTrue(s.startswith('<svg') and s.endswith('</svg>'))
        with self.assertRaises(ValueError):
            qr.matrix('x' * 300)


FINGERPRINT_URL_M0 = '3b3c6cd4132fe62e'

if __name__ == '__main__':
    unittest.main()
