import ast
import operator
import math
from tools.registry import tool

ALLOWED_MATH_FUNCS = {
    k: v for k, v in math.__dict__.items() if not k.startswith("__") and callable(v)
}

ALLOWED_MATH_CONSTANTS = {
    'pi': math.pi, 'e': math.e, 'inf': math.inf, 'nan': math.nan, 'tau': math.tau
}

OPERATORS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod, ast.Pow: operator.pow,
    ast.BitXor: operator.xor, ast.USub: operator.neg, ast.UAdd: operator.pos,
}

def _eval_ast(node):
    if isinstance(node, ast.Expression):
        return _eval_ast(node.body)
    elif isinstance(node, ast.Constant):
        if not isinstance(node.value, (int, float)):
            raise TypeError("Only numbers are permitted")
        return node.value
    elif isinstance(node, ast.BinOp):
        return OPERATORS[type(node.op)](_eval_ast(node.left), _eval_ast(node.right))
    elif isinstance(node, ast.UnaryOp):
        return OPERATORS[type(node.op)](_eval_ast(node.operand))
    elif isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise TypeError("Only math functions are allowed")
        func_name = node.func.id
        if func_name not in ALLOWED_MATH_FUNCS:
            raise ValueError(f"Function {func_name} not available")
        args = [_eval_ast(arg) for arg in node.args]
        return ALLOWED_MATH_FUNCS[func_name](*args)
    elif isinstance(node, ast.Name):
        if node.id in ALLOWED_MATH_CONSTANTS:
            return ALLOWED_MATH_CONSTANTS[node.id]
        raise ValueError(f"Variable {node.id} not available")
    else:
        raise TypeError(f"Unsupported mathematical operation")

@tool
def calculate(expression: str) -> str:
    """Evaluate a mathematical expression safely.
    Supports basic operators (+, -, *, /, **, %) and standard math functions (e.g., sin, cos, sqrt).
    """
    try:
        node = ast.parse(expression, mode='eval')
        result = _eval_ast(node)
        
        if isinstance(result, float):
            result = round(result, 10)
            if result.is_integer():
                result = int(result)
                
        return str(result)
    except Exception as e:
        return f"Error evaluating expression: {e}"
