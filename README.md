# OpenDataLoader PDF API

使用 [opendataloader-pdf](https://github.com/opendataloader-project/opendataloader-pdf)
实现兼容的 `POST /file_parse` 接口。

## 启动

需要 [uv](https://docs.astral.sh/uv/)、Java 11+、`pdfinfo`（Poppler）以及 Hybrid 依赖：

```bash
uv sync
uv run opendataloader-pdf-hybrid --host 127.0.0.1 --port 5002 --force-ocr --ocr-lang ch_sim --enrich-picture-description &
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

运行测试：

```bash
uv run pytest
```

也可以使用 Docker Compose（API 和 Hybrid OCR 在同一个容器中运行）：

```bash
docker compose up --build
```

Docker 构建阶段会预下载 SmolVLM、EasyOCR 检测模型和中文 `zh_sim_g2` 识别模型并打入镜像，
通过 `DOCLING_ARTIFACTS_PATH` 提供给 Docling，运行时不需要访问外网。模型文件会让镜像变大，
构建机器需要临时联网。若只想构建基础镜像，
可使用 `docker build --build-arg PRELOAD_HYBRID_MODELS=0 ...`，但运行时需要自行挂载模型缓存。

Swagger 文档：<http://localhost:8000/docs>

## 调用

```bash
curl -X POST 'http://localhost:8000/file_parse' \
  -F 'files=@./example.pdf' \
  -F 'return_md=true' \
  -F 'return_content_list=true' \
  -F 'return_images=true' \
  -o output.json
```

批量上传时重复使用 `files`：

```bash
curl -X POST 'http://localhost:8000/file_parse' \
  -F 'files=@./a.pdf' \
  -F 'files=@./b.pdf'
```

`start_page_id` 和 `end_page_id` 是从 0 开始且包含结束页。服务会先使用 OpenDataLoader
本地 Java pipeline 解析；如果结果中包含图片，会记录切换原因并改用 `docling-fast` Hybrid
后端以 `full` 模式重跑。Hybrid 服务启用了中文 OCR 和图片描述；Hybrid 失败不会静默回退，
日志会显示具体引擎、服务地址、耗时和错误。

日志示例：

```text
task=abcd1234 event=parse_start engine=pipeline ...
task=abcd1234 event=engine_switch from=pipeline to=docling-fast reason=images_detected
task=abcd1234 event=parse_finished engine=docling-fast elapsed_s=...
```

Hybrid 调用前会检查 `/health`；不可达时记录 `hybrid_unhealthy` 并返回解析失败，
成功时记录 `hybrid_healthy`。Java 解析器的原始日志也会输出，失败详情会附在任务错误中。
结束页超过实际页数时，按每份 PDF 分别截断；起始页超出实际页数时返回错误。

Docker Compose 配置会在同一个容器中启动两个进程：Hybrid OCR 监听 `5002`，API 监听
`8000`。入口脚本会等待 Hybrid `/health` 通过后再启动 API。可使用
`docker compose up -d --build` 启动服务，用 `docker compose logs -f pdfservice` 查看日志。
如果日志出现 `url=http://127.0.0.1:5002`，这是单容器内的正常地址。

当前实现面向 PDF。OpenDataLoader 不原生支持 Office 文件，也没有与 MinerU 完全等价的
`formula_enable` / `table_enable` 开关；这些表单字段会被接受以保持调用兼容。

`content_list` 中的 `bbox` 与 MinerU 保持一致：格式为 `[x0, y0, x1, y1]`，
使用左上角原点，并依据每页实际宽高分别归一化到 `0-1000` 的整数范围。
