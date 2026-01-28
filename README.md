# Qwen-TTS-WS-HTTP

该项目将阿里云 DashScope 的 Qwen-TTS 实时 WebSocket 接口封装为易于使用的 HTTP 接口，支持标准音频文件下载和 SSE (Server-Sent Events) 流式音频推送。

## 功能特性

- **简单 HTTP POST**: 一次性获取完整音频（自动封装为 WAV 格式）。
- **SSE 流式支持**: 实时推送音频分片（Base64 编码的 PCM），降低首包延迟。
- **多端存储支持**: 支持将合成音频保存至本地或上传至 S3 兼容存储（如 AWS S3, Minio）。
- **灵活的返回方式**: 支持直接返回音频二进制数据，或返回音频存储后的访问 URL。
- **自动格式转换**: 内部处理 PCM 到 WAV 的转换，方便播放器直接调用。
- **健康检查**: 提供 `/health` 接口用于服务监控。

## 环境要求

- Python 3.13+
- 阿里云 DashScope API Key

## 安装

1. 克隆项目到本地。
2. 安装依赖：
   ```bash
   pip install dashscope fastapi uvicorn
   # 或者使用项目自带的 uv (推荐)
   uv sync
   ```

## 配置

项目使用 [dynaconf](https://www.dynaconf.com/) 进行配置管理。你可以通过以下方式配置项目：

### 1. 配置文件

在项目根目录下，你可以使用 `settings.yaml` 来配置非敏感信息：

```yaml
default:
  dashscope:
    url: "wss://dashscope.aliyuncs.com/api-ws/v1/realtime"
  server:
    host: "0.0.0.0"
    port: 9999
  enableSave: true # 是否保存合成后的音频
  storageType: "local" # 存储类型：local 或 s3
  outputDir: "./output" # 本地存储目录

  # S3 存储配置 (当 storageType 为 s3 时必填)
  s3:
    bucket: "your-bucket-name"
    endpoint: "http://localhost:9000" # S3 服务地址
    region: "us-west-1"
    publicUrlPrefix: "" # 可选，自定义域名协议头
    urlType: "public" # 链接类型：public 或 private
    expiresIn: 3600 # 私有链接有效期（秒）
```

敏感信息（如 API Key）建议存放在 `.secrets.yaml`（该文件已被 `.gitignore` 忽略）：

```yaml
dashscope_api_key: "您的_DASHSCOPE_API_KEY"
# 也可以在这里存放 S3 密钥
s3:
  accessKeyId: "..."
  accessKeySecret: "..."
```

### 2. 环境变量

你仍然可以使用环境变量来设置配置项。环境变量的前缀通常是 `DYNACONF_`（除非有特殊配置），但对于某些敏感信息，我们也支持直接读取：

- `DASHSCOPE_API_KEY`: 阿里云 DashScope 的 API Key。

对于其他配置项，请参考 [dynaconf](https://www.dynaconf.com/envvars/) 给出的命名格式进行配置。例如，设置服务器端口：
```bash
export DYNACONF_SERVER__PORT=9001
```

## 运行

执行以下命令启动服务：

```bash
python main.py
```

服务默认监听 `0.0.0.0:9999`。

## API 文档

### 1. 文本转语音 (返回 WAV 文件)

将文本转换为完整的 WAV 音频文件。

- **URL**: `/tts`
- **方法**: `POST`
- **Content-Type**: `application/json`

**请求体**:

| 字段 | 类型 | 必填 | 默认值 | 说明                                                                                                                                                                                                                                                         |
| :--- | :--- | :--- | :--- |:-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `text` | string | 是 | - | 需要合成的文本内容                                                                                                                                                                                                                                                  |
| `model` | string | 是 | - | 使用的模型名称。具体信息参考：[DashScope 模型列表](https://help.aliyun.com/zh/model-studio/user-guide/qwen-tts-realtime-api?spm=a2c4g.11186623.0.i1#9478426090u7g) |
| `voice` | string | 否 | `Cherry` | 选用的音色名称                                                                                                                                                                                                                                                    |
| `return_url` | boolean | 否 | `false` | 是否返回音频 URL 而不是二进制数据（需开启存储功能）                                                                                                                                                                                                                  |

**示例请求 (cURL - 返回二进制)**:

```bash
curl -X POST http://localhost:9999/tts \
  -H "Content-Type: application/json" \
  -d '{
    "text": "你好，欢迎使用通义千问语音合成服务。",
    "model": "qwen3-tts-flash-realtime",
    "voice": "Cherry"
  }' --output output.wav
```

**示例请求 (cURL - 返回 URL)**:

```bash
curl -X POST http://localhost:9999/tts \
  -H "Content-Type: application/json" \
  -d '{
    "text": "你好，欢迎使用通义千问语音合成服务。",
    "model": "qwen3-tts-flash-realtime",
    "return_url": true
  }'
```

**示例返回 (JSON)**:
```json
{
  "url": "http://localhost:9999/output/xxxx.wav"
}
```

### 2. 流式文本转语音 (SSE)

通过 SSE 协议实时获取音频片段。

- **URL**: `/tts_stream`
- **方法**: `POST`
- **Content-Type**: `application/json`

**请求体**: 同上。

**示例请求 (cURL)**:

```bash
curl -X POST http://localhost:9999/tts_stream \
  -H "Content-Type: application/json" \
  -d '{
    "text": "你好，这是一个流式输出测试。",
    "model": "qwen3-tts-flash-realtime",
    "voice": "Cherry"
  }'
```

**返回内容示例**:

```text
data: {"audio": "...", "is_end": false}
data: {"audio": "...", "is_end": false}
...
data: {"is_end": true, "url": "...", "usage_characters": "12"}
```
*注：`audio` 字段为 Base64 编码的 PCM (24000Hz, Mono, 16bit) 数据。如果开启了存储功能，最后一条消息会包含音频的 `url`。`usage_characters` 表示本次合成消耗的字符数。*

### 3. 健康检查

- **URL**: `/health`
- **方法**: `GET`

**返回**: `{"status": "ok"}`

## 响应头信息

在 `/tts` 接口返回时，会包含以下自定义响应头：
- `X-Session-Id`: 本次合成的会话 ID。
- `X-First-Audio-Delay`: 首包音频延迟（毫秒）。
- `X-Usage-Characters`: 本次合成消耗的字符数。
- `Content-Type`: `audio/wav` (返回二进制时) 或 `application/json` (返回 URL 时)。
