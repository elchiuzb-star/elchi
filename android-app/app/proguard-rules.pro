# kotlinx.serialization: keep generated serializers of the API models (uz.elchi.app.api.generated).
-keepattributes *Annotation*, InnerClasses
-keepclassmembers class uz.elchi.app.api.** {
    *** Companion;
    kotlinx.serialization.KSerializer serializer(...);
}
-keep,includedescriptorclasses class uz.elchi.app.api.**$$serializer { *; }
