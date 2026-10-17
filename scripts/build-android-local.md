# TalkTool · Android 本地打包（对齐小树学堂）

uni-app（非 Capacitor）本地出 APK 不能 `gradlew assembleDebug` 了事。
标准路径与小树学堂相同：**CLI/HBuilderX 生成 app 资源 → 放入 DCloud App 离线 SDK 工程 → Android Studio / Gradle 出包**。

生产 API：`https://talk.aidigitcloud.cn`（见 `frontend/.env.production` 的 `VITE_API_BASE`）。
域名 DNS 未生效前，App 里请求会失败，请先配好 `talk.aidigitcloud.cn` → `111.228.6.222`。

## 两条路怎么选

| 方式 | 适合 | 说明 |
| --- | --- | --- |
| **HBuilderX 云打包** | 最快出安装包 | 填好 DCloud `appid` 后：发行 → 原生 App-云打包 → Android |
| **本地离线 SDK** | 要自己签证书 / 改原生 | 见下方步骤；与小树 `scripts/build-android-local.md` 同一套 |

## 本机环境

| 项 | 说明 |
| --- | --- |
| Android SDK | 建议 `~/Library/Android/sdk`，`export ANDROID_HOME=...` |
| Java | 建议 `export JAVA_HOME=/opt/homebrew/opt/openjdk@21` |
| HBuilderX | `/Applications/HBuilderX.app`（`brew install --cask hbuilderx`） |
| Android Studio | 导入离线 SDK 工程时建议安装 |
| DCloud `appid` | `frontend/src/manifest.json` 顶层目前为空 → 到 [开发者中心](https://dev.dcloud.net.cn/) 创建应用后填入 |
| App 离线 SDK | 与 HBuilderX **同号版本**下载，解压到如 `~/DCloud/Android-SDK/`（**不要进 git**） |

一键检查：

```bash
./scripts/check-android-local.sh
```

## 你必须完成的步骤

### 1. 申请 DCloud appid（以及离线打包用的 AppKey）

1. 打开 [https://dev.dcloud.net.cn/](https://dev.dcloud.net.cn/) 创建应用  
2. 把生成的 `__UNI__xxxxxx` 填进 `frontend/src/manifest.json` 的 `"appid"`  
3. 离线打包还需申请 **Android 包名对应的 AppKey**，填入离线工程 `AndroidManifest.xml` 的 `dcloud_appkey`  
   建议包名：`cn.aidigitcloud.talktool`

没有 appid，云打包 / 本地打包都走不通；没有 AppKey，离线 APK 无法正常启动。

### 2. 生成 App 资源

```bash
export JAVA_HOME=/opt/homebrew/opt/openjdk@21   # 按本机调整
cd frontend
npm install
npm run build:app
```

CLI 产物：

```
frontend/dist/build/app/
```

也可用 HBuilderX：打开 `frontend` 目录 →「发行 → 原生 App-本地打包 → 生成本地打包 App 资源」。

### 3A. 云打包（推荐先走这条）

1. HBuilderX 打开 `frontend`  
2. 确认 `manifest.json` 已填 `appid`，权限含麦克风  
3. 发行 → 原生 App-云打包 → 勾选 Android（可先打「使用 DCloud 公用证书」的测试包）  
4. 打包完成后下载 `.apk` 装到手机  

### 3B. 本地离线 SDK 出包

1. 下载与 HBuilderX **同版本**的 [Android 离线 SDK](https://nativesupport.dcloud.net.cn/AppDocs/download/android)  
2. 解压后打开 `HBuilder-Integrate-AS`，用其中的 `simpleDemo`  
3. 把 `frontend/dist/build/app/`（或以 appid 命名的资源目录）拷进：  
   `simpleDemo/src/main/assets/apps/<appid>/`  
4. 改 `assets/data/dcloud_control.xml` 的 `appid`，与目录名、`manifest.json` 一致  
5. `AndroidManifest.xml` 填 `dcloud_appkey`；`build.gradle` 设  
   `applicationId "cn.aidigitcloud.talktool"`，`versionName` / `versionCode` 与 manifest 对齐  
6. Android Studio 打开工程 → `Build → Build APK(s)`  
   Debug 典型路径：`simpleDemo/build/outputs/apk/debug/simpleDemo-debug.apk`

官方说明：[Android 离线打包](https://nativesupport.dcloud.net.cn/AppDocs/usesdk/android)。

## 不要做的事

- 不要把离线 SDK、HBuilderX、`.apk`、密钥、`.keystore` 提交进 git  
- 不要照搬 Capacitor / `janpanlearn/android`（与 uni-app 离线 SDK 不是同一套）  
- 不要在 `appid` 仍为空时以为「已经能装包」  
