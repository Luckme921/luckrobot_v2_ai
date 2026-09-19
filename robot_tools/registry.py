"""Small allowlisted local dispatcher; no eval, shell strings or arbitrary URLs."""
from shared.timing import measure

def validate(arguments, schema):
    if not isinstance(arguments, dict):
        raise ValueError("arguments must be an object")
    if set(arguments) - set(schema["properties"]):
        raise ValueError("unknown argument")
    if not set(schema.get("required", ())).issubset(arguments):
        raise ValueError("missing argument")
    for key, value in arguments.items():
        spec = schema["properties"][key]
        kind = spec["type"]
        if kind == "string" and (not isinstance(value, str) or len(value) > spec.get("maxLength", 4000)):
            raise ValueError("invalid string")
        if kind == "integer" and (type(value) is not int or
                not spec.get("minimum", -1e9) <= value <= spec.get("maximum", 1e9)):
            raise ValueError("invalid integer")
        if "enum" in spec and value not in spec["enum"]:
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
