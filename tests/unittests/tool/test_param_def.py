"""ParamDef 参数定义系统测试。

测试目标：fabrica/tool.py 中的 ParamType / ParamDef / ParamDefSchema / validate_param
覆盖：枚举值、dataclass 默认值、Schema 转换、六种校验规则
"""

import unittest

from fabrica.tool import (
    ParamDef,
    ParamDefSchema,
    ParamType,
    validate_param,
)


class TestParamType(unittest.TestCase):
    """ParamType 枚举测试集。"""

    def test_enum_values(self):
        """10 种参数类型枚举值应正确。"""
        expected = {
            "STRING": "str",
            "INTEGER": "int",
            "FLOAT": "float",
            "BOOLEAN": "bool",
            "PATH": "path",
            "FILE": "file",
            "DIRECTORY": "dir",
            "SELECT": "select",
            "MULTI_SELECT": "multi_select",
            "PASSWORD": "password",
        }
        self.assertEqual(len(ParamType), len(expected))
        for name, value in expected.items():
            self.assertEqual(getattr(ParamType, name).value, value)

    def test_enum_inherits_str(self):
        """枚举值应可直接作为字符串比较。"""
        self.assertEqual(ParamType.STRING, "str")
        self.assertEqual(ParamType.MULTI_SELECT, "multi_select")


class TestParamDef(unittest.TestCase):
    """ParamDef 数据类测试集。"""

    def test_defaults(self):
        """ParamDef 默认值应正确。"""
        p = ParamDef(key="k")
        self.assertEqual(p.label, "")
        self.assertEqual(p.type, "str")
        self.assertIsNone(p.default)
        self.assertFalse(p.required)
        self.assertEqual(p.description, "")
        self.assertEqual(p.placeholder, "")
        self.assertEqual(p.options, [])
        self.assertEqual(p.validation, {})

    def test_custom_fields(self):
        """ParamDef 自定义字段应正确。"""
        p = ParamDef(
            key="t",
            label="阈值",
            type="float",
            default=0.5,
            required=True,
            description="描述",
        )
        self.assertEqual(p.key, "t")
        self.assertEqual(p.label, "阈值")
        self.assertEqual(p.type, "float")
        self.assertEqual(p.default, 0.5)
        self.assertTrue(p.required)
        self.assertEqual(p.description, "描述")

    def test_options_and_validation(self):
        """options 与 validation 应正确。"""
        p = ParamDef(
            key="s",
            type="select",
            options=[("a", "A")],
            validation={"min": 0},
        )
        self.assertEqual(p.options, [("a", "A")])
        self.assertEqual(p.validation, {"min": 0})


class TestParamDefSchema(unittest.TestCase):
    """ParamDefSchema 模型测试集。"""

    def test_from_param_def(self):
        """from_param_def 应正确映射字段。"""
        p = ParamDef(
            key="t",
            label="阈值",
            type="float",
            default=0.5,
            required=True,
            validation={"min": 0},
        )
        schema = ParamDefSchema.from_param_def(p)
        self.assertEqual(schema.key, "t")
        self.assertEqual(schema.label, "阈值")
        self.assertEqual(schema.type, "float")
        self.assertEqual(schema.default, 0.5)
        self.assertTrue(schema.required)
        self.assertEqual(schema.validation, {"min": 0})

    def test_direct_construction(self):
        """直接构造 ParamDefSchema 应可用。"""
        schema = ParamDefSchema(key="k", type="int")
        self.assertEqual(schema.key, "k")
        self.assertEqual(schema.type, "int")
        self.assertEqual(schema.options, [])
        self.assertEqual(schema.validation, {})


class TestValidateParam(unittest.TestCase):
    """validate_param 校验规则引擎测试集。"""

    def test_none_skips_all_rules(self):
        """None 值应跳过所有校验返回空列表。"""
        p = ParamDef(key="k", validation={"min": 5})
        self.assertEqual(validate_param(None, p), [])

    def test_empty_rules(self):
        """无校验规则应返回空列表。"""
        p = ParamDef(key="k")
        self.assertEqual(validate_param(10, p), [])

    def test_min_passes_when_equal(self):
        """等于最小值应通过。"""
        p = ParamDef(key="k", validation={"min": 5})
        self.assertEqual(validate_param(5, p), [])

    def test_min_fails_when_below(self):
        """低于最小值应报错。"""
        p = ParamDef(key="k", validation={"min": 5})
        errors = validate_param(4, p)
        self.assertEqual(len(errors), 1)
        self.assertIn("低于最小值", errors[0])

    def test_max_passes_when_equal(self):
        """等于最大值应通过。"""
        p = ParamDef(key="k", validation={"max": 10})
        self.assertEqual(validate_param(10, p), [])

    def test_max_fails_when_above(self):
        """超过最大值应报错。"""
        p = ParamDef(key="k", validation={"max": 10})
        errors = validate_param(11, p)
        self.assertEqual(len(errors), 1)
        self.assertIn("超过最大值", errors[0])

    def test_float_min_max(self):
        """浮点数 min/max 校验应生效。"""
        p = ParamDef(key="k", validation={"min": 0, "max": 1})
        self.assertEqual(validate_param(0.5, p), [])
        self.assertEqual(len(validate_param(1.5, p)), 1)

    def test_numeric_rules_ignored_for_string(self):
        """数值规则对字符串不应生效。"""
        p = ParamDef(key="k", validation={"min": 5})
        self.assertEqual(validate_param("abc", p), [])

    def test_bool_not_treated_as_number(self):
        """布尔值不应被当作数值校验。"""
        p = ParamDef(key="k", validation={"min": 5})
        self.assertEqual(validate_param(True, p), [])

    def test_min_length_passes(self):
        """字符串长度满足最小长度应通过。"""
        p = ParamDef(key="k", validation={"min_length": 3})
        self.assertEqual(validate_param("abc", p), [])

    def test_min_length_fails(self):
        """字符串长度低于最小长度应报错。"""
        p = ParamDef(key="k", validation={"min_length": 3})
        errors = validate_param("ab", p)
        self.assertEqual(len(errors), 1)
        self.assertIn("长度低于最小值", errors[0])

    def test_max_length_passes(self):
        """字符串长度满足最大长度应通过。"""
        p = ParamDef(key="k", validation={"max_length": 3})
        self.assertEqual(validate_param("abc", p), [])

    def test_max_length_fails(self):
        """字符串长度超过最大长度应报错。"""
        p = ParamDef(key="k", validation={"max_length": 3})
        errors = validate_param("abcd", p)
        self.assertEqual(len(errors), 1)
        self.assertIn("长度超过最大值", errors[0])

    def test_pattern_matches(self):
        """正则匹配应通过。"""
        p = ParamDef(key="k", validation={"pattern": "^[a-z]+$"})
        self.assertEqual(validate_param("abc", p), [])

    def test_pattern_not_matches(self):
        """正则不匹配应报错。"""
        p = ParamDef(key="k", validation={"pattern": "^[a-z]+$"})
        errors = validate_param("ABC123", p)
        self.assertEqual(len(errors), 1)
        self.assertIn("格式不匹配", errors[0])

    def test_file_extensions_allowed(self):
        """允许的扩展名应通过。"""
        p = ParamDef(key="k", validation={"file_extensions": [".mp4", ".avi"]})
        self.assertEqual(validate_param("video.mp4", p), [])
        self.assertEqual(validate_param("video.AVI", p), [])

    def test_file_extensions_disallowed(self):
        """不允许的扩展名应报错。"""
        p = ParamDef(key="k", validation={"file_extensions": [".mp4"]})
        errors = validate_param("video.mov", p)
        self.assertEqual(len(errors), 1)
        self.assertIn("文件扩展名不允许", errors[0])

    def test_file_extensions_no_dot(self):
        """无扩展名的文件应报错。"""
        p = ParamDef(key="k", validation={"file_extensions": [".mp4"]})
        errors = validate_param("video", p)
        self.assertEqual(len(errors), 1)


if __name__ == "__main__":
    unittest.main()