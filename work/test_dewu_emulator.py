import copy
import unittest
import xml.etree.ElementTree as ET
from dewu_emulator import PACKAGE, PREFIX, extract_income, product_url


PRODUCT = {'article_no': '237153-BKGY', 'color': '黑灰', 'gender': '男款',
           'spu_id': '1168907', 'property_value_id': '561869809', 'sku_id': '601166267',
           'app_version': '5.83.0',
           'public_url': 'https://www.dewu.com/product-detail.html?sourceName=h5&spuId=1168907&propertyValueId=561869809&skuId=601166267'}


def panel(article='237153-BKGY', color='黑灰', gender='男款', channel=True, income=True,
          rows=(('41.5', '¥167.6'), ('42.5', '¥173.54'))):
    root = ET.Element('hierarchy')
    frame = ET.SubElement(root, 'node', package=PACKAGE)
    def node(parent, suffix='', text='', selected=False):
        return ET.SubElement(parent, 'node', {'resource-id': PREFIX + suffix if suffix else '',
                                             'text': text, 'selected': str(selected).lower(), 'package': PACKAGE})
    node(frame, 'tvArticleNumber', '货号：' + article)
    node(frame, 'tvPropName', 'shoe ' + gender + ' ' + color)
    node(frame, text='普通发货', selected=channel)
    node(frame, 'itemIncome', '预计收入', income)
    node(frame, 'tvName', color, True)
    for size, price in rows:
        row = node(frame)
        node(row, 'tvName', size)
        node(row, 'tvPrice', price)
    return root


class DirectDewuTest(unittest.TestCase):
    def test_public_ids_build_registered_route_without_search(self):
        url = product_url(PRODUCT)
        self.assertEqual(url, 'https://m.dewu.com/router/product/ProductDetail?spuId=1168907&propertyValueId=561869809&skuId=601166267')
        self.assertNotIn('search', url.lower())

    def test_changed_host_id_or_layout_cannot_launch(self):
        for field, value in [('public_url', 'https://attacker.example/product-detail.html?spuId=1168907'),
                             ('spu_id', '1168908'), ('sku_id', '1&touch x'), ('app_version', '6.0')]:
            product = copy.deepcopy(PRODUCT)
            product[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                product_url(product)

    def test_income_values_are_read_without_fee_calculation(self):
        self.assertEqual(extract_income(panel(), PRODUCT), [
            {'size': '41.5', 'estimated_income': 167.6}, {'size': '42.5', 'estimated_income': 173.54}])

    def test_article_color_gender_channel_and_tab_must_match(self):
        for field, value in [('article', 'different'), ('color', '白'), ('gender', '女款'),
                             ('channel', False), ('income', False)]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                extract_income(panel(**{field: value}), PRODUCT)

    def test_invalid_and_duplicate_price_rows_are_rejected(self):
        for rows in [(('42.5', '¥NaN'),), (('42.5', '¥-1'),), (('42.5', '待核价'),),
                     (('42.5', '¥173.54'), ('42.5', '¥999')), ()]:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                extract_income(panel(rows=rows), PRODUCT)

    def test_foreign_app_overlay_is_not_treated_as_product_data(self):
        root = panel()
        ET.SubElement(root, 'node', package='another.app')
        with self.assertRaises(ValueError):
            extract_income(root, PRODUCT)
