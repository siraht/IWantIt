from unittest import TestCase

from iwantit.canonical import set_field


class CanonicalTests(TestCase):
    def test_source_priority(self) -> None:
        data = {}
        set_field(data, "title", "From URL", source="url")
        set_field(data, "title", "From Input", source="input")
        self.assertEqual(data["canonical"]["fields"]["title"], "From Input")
