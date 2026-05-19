import unittest

from src.invoice_parser import parse_invoice_line, parse_invoice_text


class InvoiceParserTest(unittest.TestCase):
    def test_parses_user_example_and_ignores_accounting_code(self):
        line = "21 - КА000000003 - Цепь(Цепь ЦА604 (2010001488255)) - 1 - шт - - 2,43 - 18 230"

        item = parse_invoice_line(line)

        self.assertIsNotNone(item)
        self.assertEqual(item.short_code, "ЦА604")
        self.assertEqual(item.long_id, "2010001488255")
        self.assertEqual(item.weight, "2.43")
        self.assertEqual(item.total, "18230")

    def test_parses_lines_from_photo_like_invoice(self):
        text = """
        1 КА000000005 Браслет (Браслет БА6113 (2010001488194)) 1 шт 2,67 9 030,00 20 030,00
        15 КА000000009 Серьги (Серьги СА177 (2010001455493)) 1 шт 2,27 6 140,00 16 140,00
        """

        items = parse_invoice_text(text)

        self.assertEqual([item.short_code for item in items], ["БА6113", "СА177"])
        self.assertEqual([item.long_id for item in items], ["2010001488194", "2010001455493"])
        self.assertEqual([item.weight for item in items], ["2.67", "2.27"])
        self.assertEqual([item.total for item in items], ["20030", "16140"])

    def test_parses_commission_receipt_ocr_with_latin_codes(self):
        text = """
        Колье KA230 (2010001494683) ЕТ — ao, ae
        Кольцо KA231 (2010001494690) aa [10030,00] 030,00
        Крест MA230 (2010001494706) aS "87 Г 13300,00] 300,00 —
        [в СерыибАвза (2010001494751) [9.29] 929] 66050,00]
        = Серьги CA233 (2010001494768) [3,82] 3,82] 27 160,00}
        """

        items = parse_invoice_text(text)

        self.assertEqual([item.short_code for item in items], ["KA230", "KA231", "MA230", "CA233"])
        self.assertEqual([item.long_id for item in items], ["2010001494683", "2010001494690", "2010001494706", "2010001494768"])
        self.assertEqual(items[1].total, "10030")
        self.assertEqual(items[3].weight, "3.82")
        self.assertEqual(items[3].total, "27160")


if __name__ == "__main__":
    unittest.main()
