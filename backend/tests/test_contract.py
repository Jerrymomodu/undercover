from backend.main import app


def test_every_operation_has_an_id_a_docstring_and_only_required_inputs():
    schema = app.openapi()
    components = schema["components"]["schemas"]
    for path, methods in schema["paths"].items():
        for method, operation in methods.items():
            where = f"{method.upper()} {path}"
            assert operation["operationId"], where
            assert operation["description"].count("\n") == 0, where
            assert all(p["required"] for p in operation.get("parameters", [])), where
            body = operation.get("requestBody")
            if body:
                assert body["required"], where
                ref = body["content"]["application/json"]["schema"]["$ref"]
                model = components[ref.rsplit("/", 1)[-1]]
                assert set(model.get("required", [])) == set(model["properties"]), where
