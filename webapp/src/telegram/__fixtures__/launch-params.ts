/**
 * Synthetic Telegram launch parameters for tests.
 *
 * Built here rather than copied from a real session. The SDK only validates the
 * *shape* of a payload - it never checks the HMAC, which is the backend's job - so
 * the tests that exercise the dev mock need a well-formed payload and nothing more.
 *
 * That means no real user id, no real signature, and no real `hash` has any business
 * being in the test suite. Everything below is obviously fake.
 */

/** Reserved for documentation and examples; not a real account. */
export const FAKE_USER_ID = 100000001;

/**
 * Build a launch-parameter payload.
 *
 * The `hash` and `signature` are placeholders: the frontend never verifies them, and
 * a value that *would* verify is a usable credential, which is not something to keep
 * in a git-tracked file.
 */
export function fakeInitData(
  options: { userId?: number; firstName?: string; startParam?: string } = {},
): string {
  const { userId = FAKE_USER_ID, firstName = "Test", startParam } = options;

  const fields: Record<string, string> = {
    user: JSON.stringify({ id: userId, first_name: firstName }),
    auth_date: "1700000000",
    chat_instance: "-1000000000000000000",
    chat_type: "sender",
  };
  if (startParam) fields.start_param = startParam;

  // Order matters only for the byte-for-byte assertions, not for validity.
  const query = new URLSearchParams(fields);
  query.set("signature", "A".repeat(86));
  query.set("hash", "0".repeat(64));
  return query.toString();
}
