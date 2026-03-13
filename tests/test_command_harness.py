import unittest

from tests import test_commands


class CommandHarnessTests(unittest.TestCase):
    def test_command_script(self):
        self.assertEqual(test_commands.main(), 0)


if __name__ == "__main__":
    unittest.main()
