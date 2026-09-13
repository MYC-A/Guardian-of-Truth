"""Unwrap declared invocation interfaces without inferring business semantics."""


def declared_interface(schema):
    if not isinstance(schema, dict):
        return None
    if schema.get('type') == 'function':
        function = schema.get('function')
        if not isinstance(function, dict):
            return None
        # Conflicting outer names are not resolved by choosing a preferred one.
        if 'name' in schema and schema['name'] != function.get('name'):
            return None
        schema = function
    if not isinstance(schema.get('name'), str) or not schema['name']:
        return None
    return schema
