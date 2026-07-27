import unittest

from mongo_module_library import MODULES
from mongo_safe_runner import ModuleValidationError, prepare_module, validate_module


class MongoModuleTests(unittest.TestCase):
    def test_registry_has_many_unique_valid_modules(self):
        self.assertGreaterEqual(len(MODULES), 35)
        self.assertEqual(len(MODULES), len({item["_id"] for item in MODULES}))
        for item in MODULES:
            validate_module(item)

    def test_write_modules_are_explicitly_allowlisted(self):
        writes = [item for item in MODULES if item["risk_level"] == "write"]
        self.assertGreaterEqual(len(writes), 3)
        for item in writes:
            self.assertTrue(item["allowed_targets"])
            with self.assertRaises(ModuleValidationError):
                prepare_module(item)
            prepared = prepare_module(item, allow_writes=True)
            self.assertEqual(set(prepared["write_targets"]), set(item["allowed_targets"]))

    def test_forbidden_javascript_is_rejected(self):
        bad = {
            **MODULES[0],
            "_id": "bad_javascript_module",
            "private": {
                "node_function": {
                    "edge": [{
                        "pipeline": [{
                            "$project": {
                                "x": {
                                    "$function": {
                                        "body": "x",
                                        "args": [],
                                        "lang": "js",
                                    }
                                }
                            }
                        }]
                    }]
                }
            },
        }
        with self.assertRaises(ModuleValidationError):
            validate_module(bad)

    def test_unknown_parameter_is_rejected(self):
        with self.assertRaises(ModuleValidationError):
            prepare_module(MODULES[0], {"UNDECLARED": 1})


if __name__ == "__main__":
    unittest.main()
