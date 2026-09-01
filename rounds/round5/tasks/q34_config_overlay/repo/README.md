# Layered configuration incident

`merge_config(base, overlay)` applies a tenant overlay to inherited configuration.
The service passes JSON-decoded dictionaries to this function.

Required behavior:

- an absent overlay key retains the inherited value;
- `false`, `0`, and the empty string are valid replacement values;
- mapping values merge recursively and preserve unspecified siblings;
- `null` is a tombstone that removes the addressed inherited key at any depth;
- lists and non-mapping values replace rather than merge or append;
- neither input nor any object reachable from an input may be mutated through the
  returned value.

The result must be a fresh deep structure. Run `python3 run_tests.py`. Do not edit the
public test runner or operator note.
