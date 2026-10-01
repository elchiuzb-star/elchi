import Foundation

extension LocaleStore {
    /// What a person reads when a request fails: the dictionary's sentence for the server code (`error.<CODE>`),
    /// the server's own message when the code is not in the dictionary yet, and "no connection" when nothing came
    /// back. Never a raw code, never "try again" for a business rule.
    public func errorText(_ error: Error) -> String {
        guard let error = error as? APIError else { return t("error.fallback") }
        if error.code == APIError.network { return t("error.offline") }
        return tOrNil("error.\(error.code)") ?? (error.message.isEmpty ? t("error.fallback") : error.message)
    }
}
