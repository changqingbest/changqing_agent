import unittest

from app.prompts import get_prompt_catalog


class PromptTemplateTests(unittest.TestCase):
    def test_catalog_has_unique_categories_and_templates(self) -> None:
        catalog = get_prompt_catalog()
        category_ids = [item["id"] for item in catalog["categories"]]
        template_ids = [item["id"] for item in catalog["templates"]]
        self.assertEqual(len(category_ids), 8)
        self.assertEqual(len(category_ids), len(set(category_ids)))
        self.assertEqual(len(template_ids), 24)
        self.assertEqual(len(template_ids), len(set(template_ids)))
        self.assertTrue(all(item["category"] in category_ids for item in catalog["templates"]))

    def test_templates_have_complete_user_visible_fields(self) -> None:
        for template in get_prompt_catalog()["templates"]:
            with self.subTest(template=template["id"]):
                self.assertTrue(template["title"].strip())
                self.assertTrue(template["description"].strip())
                self.assertTrue(template["prompt"].strip())

    def test_catalog_returns_independent_copies(self) -> None:
        first = get_prompt_catalog()
        first["templates"][0]["title"] = "changed"
        self.assertNotEqual(get_prompt_catalog()["templates"][0]["title"], "changed")


if __name__ == "__main__":
    unittest.main()
