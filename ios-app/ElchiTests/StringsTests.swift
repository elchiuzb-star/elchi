import Testing
@testable import Elchi

@MainActor
struct StringsTests {
    @Test func bothLanguagesResolveAndFillPlaceholders() {
        let store = LocaleStore()
        store.set(.uz)
        #expect(store.t("auth.otpLabel", ("length", 4)) == "4 xonali kod")
        store.set(.ru)
        #expect(store.t("auth.otpLabel", ("length", 4)) == "Код из 4 цифр")
        #expect(store.tOrNil("error.NO_SUCH_CODE_EVER") == nil)
        store.set(.uz)
    }
}
