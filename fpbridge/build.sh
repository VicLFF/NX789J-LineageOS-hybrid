#!/bin/bash
# Build the fingerprint-debug bridge APK (com.nx.fpb).
#
# It binds to com.fingerprint.sensorservice/.UdfpsMessageService and sends
# sendMessageInfo(msg=6) — the only call that moves ZTE's UDFPS state machine out of
# IDLE. Used while diagnosing the fingerprint stack; harmless on its own.
#
# Run inside a LineageOS source tree after `source build/envsetup.sh` + `lunch`.
set -e

AL=${ANDROID_BUILD_TOP:?run from a lunch-ed shell}
here=$(cd "$(dirname "$0")" && pwd)
out=$here/build
rm -rf "$out"; mkdir -p "$out/classes" "$out/dex"

AJ=$(ls "$AL"/prebuilts/sdk/*/public/android.jar | tail -1)
D8=$AL/out/host/linux-x86/bin/d8
AAPT2=$AL/out/host/linux-x86/bin/aapt2
ZIPALIGN=$AL/out/host/linux-x86/bin/zipalign
SECDIR=$AL/build/make/target/product/security
APKSIGNER_JAR=$AL/prebuilts/sdk/tools/linux/lib/apksigner.jar

javac -source 17 -target 17 -classpath "$AJ" -d "$out/classes" "$here/Main.java"
"$D8" --lib "$AJ" --min-api 30 --output "$out/dex" "$out"/classes/com/nx/fpb/*.class
"$AAPT2" link -o "$out/base.apk" -I "$AJ" --manifest "$here/AndroidManifest.xml" \
        --min-sdk-version 30 --target-sdk-version 36
cp "$out/base.apk" "$out/app.apk"
(cd "$out/dex" && zip -q "$out/app.apk" classes.dex)
"$ZIPALIGN" -f 4 "$out/app.apk" "$out/app-aligned.apk"
java -jar "$APKSIGNER_JAR" sign \
        --key "$SECDIR/platform.pk8" --cert "$SECDIR/platform.x509.pem" \
        --out "$out/app-signed.apk" "$out/app-aligned.apk"
java -jar "$APKSIGNER_JAR" verify "$out/app-signed.apk"
echo "==> $out/app-signed.apk"
