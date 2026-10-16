"""Box-only check: the builder's key file exists and is the expected key. Skips anywhere else. Never prints the key."""
import hashlib, os, unittest

KEY_FILE = "/home/box/.saba/desearch_api_key"


@unittest.skipUnless(os.path.isfile(KEY_FILE), "builder key file not present")
class BoxKey(unittest.TestCase):
    def test_key_fingerprint(self):
        k = open(KEY_FILE).read().strip()
        self.assertEqual(hashlib.sha256(k.encode()).hexdigest()[:8], "a44f278b")


if __name__ == "__main__":
    unittest.main()
