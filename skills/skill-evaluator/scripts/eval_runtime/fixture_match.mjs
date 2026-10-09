export function deepContains(actual, expected) {
  if (expected && typeof expected === "object" && !Array.isArray(expected)) {
    return Boolean(actual)
      && typeof actual === "object"
      && !Array.isArray(actual)
      && Object.entries(expected).every(
      ([key, value]) => key in actual && deepContains(actual[key], value),
      );
  }
  if (Array.isArray(expected)) {
    return Array.isArray(actual) && expected.every(
      (item) => actual.some((candidate) => deepContains(candidate, item)),
    );
  }
  return actual === expected;
}

export function jsonStrictEqual(actual, expected) {
  if (typeof actual === "number" || typeof expected === "number") {
    return typeof actual === "number" && typeof expected === "number" && actual === expected;
  }
  if (Array.isArray(actual) || Array.isArray(expected)) {
    return Array.isArray(actual)
      && Array.isArray(expected)
      && actual.length === expected.length
      && actual.every((item, index) => jsonStrictEqual(item, expected[index]));
  }
  if (actual && expected && typeof actual === "object" && typeof expected === "object") {
    const actualKeys = Object.keys(actual);
    const expectedKeys = Object.keys(expected);
    return actualKeys.length === expectedKeys.length
      && actualKeys.every(
        (key) => Object.hasOwn(expected, key) && jsonStrictEqual(actual[key], expected[key]),
      );
  }
  return typeof actual === typeof expected && actual === expected;
}

export function fixtureArgsMatch(fixture, args) {
  return Object.hasOwn(fixture, "args_exact")
    ? jsonStrictEqual(args, fixture.args_exact)
    : deepContains(args, fixture.args_contain || {});
}
