"""Small allowlisted local dispatcher; no eval, shell strings or arbitrary URLs."""
from shared.timing import measure

def validate(value, schema):
    """Validate the subset of JSON Schema used by our allowlisted tools."""
    import math
    kind = schema.get("type")
    if kind == "object":
        if not isinstance(value, dict):
            raise ValueError("arguments must be an object")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties", True) is False and set(value) - set(properties):
            raise ValueError("unknown argument")
        if not set(schema.get("required", ())).issubset(value):
            raise ValueError("missing argument")
        for key, item in value.items():
            if key in properties:
                validate(item, properties[key])
    elif kind == "array":
        if not isinstance(value, list) or not schema.get("minItems", 0) <= len(value) <= schema.get("maxItems", 100):
            raise ValueError("invalid array")
        for item in value:
            validate(item, schema["items"])
    elif kind == "string":
        if not isinstance(value, str) or not schema.get("minLength", 0) <= len(value) <= schema.get("maxLength", 4000):
            raise ValueError("invalid string")
    elif kind in {"integer", "number"}:
        if type(value) not in ({int} if kind == "integer" else {int, float}) or not math.isfinite(value):
            raise ValueError("invalid number")
        if not schema.get("minimum", -math.inf) <= value <= schema.get("maximum", math.inf):
            raise ValueError("number outside allowed range")
    elif kind == "boolean" and type(value) is not bool:
        raise ValueError("invalid boolean")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError("invalid enum")

class ToolRegistry:
    def __init__(self):
        self._tools = {}

    def register(self, name, schema, function):
        if name in self._tools:
            raise ValueError("duplicate tool")
        self._tools[name] = (schema, function)

    def execute(self, name, arguments):
        if name not in self._tools:
            return {"ok": False, "tool": name, "status": "unavailable",
                    "executed": False, "message": "这个功能暂时不可用。"}
        schema, function = self._tools[name]
        try:
            validate(arguments, schema)
        except ValueError:
            return {"ok": False, "tool": name, "status": "rejected",
                    "executed": False, "message": "工具参数不正确，请再说具体一点。"}
        with measure("local_tool_" + name):
            try:
                result = function(**arguments)
                return {"tool": name, **result}
            except Exception as exc:
                print(f"[TOOL] {name} failed: {type(exc).__name__}", flush=True)
                return {"ok": False, "tool": name, "status": "error",
                        "executed": False, "message": "这个操作暂时没有完成，请稍后重试。"}
