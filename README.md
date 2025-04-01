# S3桶迁移工具

这个工具用于将支持S3协议的存储库完整地迁移到另一个支持S3协议的存储库中。工具支持多线程操作、多个桶名的批量迁移，并能处理多层级目录结构。

## 功能特点

- 支持多个S3桶的批量迁移
- 多线程并行处理，提高迁移效率
- 自动处理大文件的分块上传
- 保持原始文件结构和元数据
- 详细的日志记录和进度显示
- 支持任何兼容S3协议的存储服务
- 支持命令行参数和配置文件两种方式配置
- 智能错误处理和重试机制
- 自动跳过不存在的文件
- 失败对象详细报告和日志
- 特别优化对Cloudflare R2的支持

## 安装依赖

```bash
pip install -r requirements.txt
```

## 使用方法

### 1. 使用命令行参数

```bash
python main.py --source-endpoint SOURCE_S3_URL \
               --source-access-key SOURCE_ACCESS_KEY \
               --source-secret-key SOURCE_SECRET_KEY \
               --target-endpoint TARGET_S3_URL \
               --target-access-key TARGET_ACCESS_KEY \
               --target-secret-key TARGET_SECRET_KEY \
               --buckets "bucket1,bucket2,bucket3" \
               --max-workers 10 \
               --chunk-size 8388608
```

对于Cloudflare R2作为源存储，添加`--is-source-r2`参数：

```bash
python main.py --source-endpoint "https://<accountid>.r2.cloudflarestorage.com" \
               --source-access-key "R2_ACCESS_KEY" \
               --source-secret-key "R2_SECRET_KEY" \
               --is-source-r2 \
               --target-endpoint "http://target-s3.example.com" \
               --target-access-key "target_access_key" \
               --target-secret-key "target_secret_key" \
               --buckets "my-bucket"
```

### 2. 使用配置文件

创建一个配置文件，例如 `config.ini`（可以参考 `config.example.ini` 创建）:

```ini
[source]
endpoint = http://source-s3.example.com
access_key = source_access_key
secret_key = source_secret_key
is_r2 = false  # 设置为true表示源存储为Cloudflare R2

[target]
endpoint = http://target-s3.example.com
access_key = target_access_key
secret_key = target_secret_key

[migration]
buckets = bucket1,bucket2,bucket3
max_workers = 10
chunk_size = 8388608
```

然后使用 `--config` 参数运行程序:

```bash
python main.py --config config.ini
```

### 3. 混合使用配置文件和命令行参数

命令行参数优先级高于配置文件，可以混合使用:

```bash
python main.py --config config.ini --max-workers 20 --is-source-r2
```

## 参数说明

| 参数 | 说明 | 是否必填 |
|------|------|---------|
| `--config` | 配置文件路径 | 否 |
| `--source-endpoint` | 源S3端点URL | 是* |
| `--source-access-key` | 源S3访问密钥 | 是* |
| `--source-secret-key` | 源S3秘密密钥 | 是* |
| `--is-source-r2` | 源存储是否为Cloudflare R2 | 否 |
| `--target-endpoint` | 目标S3端点URL | 是* |
| `--target-access-key` | 目标S3访问密钥 | 是* |
| `--target-secret-key` | 目标S3秘密密钥 | 是* |
| `--buckets` | 要迁移的桶名列表，用逗号分隔 | 是* |
| `--max-workers` | 最大工作线程数 (默认: 10) | 否 |
| `--chunk-size` | 分块上传大小，单位字节 (默认: 8MB) | 否 |

(*) 如果使用配置文件，这些参数可以在配置文件中指定

## Cloudflare R2 特殊支持

当使用Cloudflare R2作为源存储时，本工具会使用专门优化的方法进行数据传输：

1. 使用`s3v4`签名版本和虚拟主机寻址样式，以确保与R2 API完全兼容
2. 避免使用在R2上可能有问题的`head_object`操作
3. 针对小文件直接使用`get_object`和`put_object`代替`copy_object`
4. 针对大文件使用优化的分块上传流程

要启用R2支持，可以：
- 在命令行参数中添加`--is-source-r2`标志
- 在配置文件的`[source]`部分设置`is_r2 = true`

## 错误处理和恢复

### 自动重试机制

工具内置了自动重试机制，对于以下类型的临时错误，会自动进行重试：

- 网络超时错误 (RequestTimeout, ConnectTimeoutError, ReadTimeoutError)
- 服务暂时不可用错误 (ServiceUnavailable, InternalError)
- 限流错误 (SlowDown)
- 操作中止错误 (OperationAborted)
- 连接错误 (ConnectionError)

重试采用指数退避策略，默认最多重试3次。

### NoSuchKey 错误处理

当源存储库中找不到某个对象时（例如文件在列表中但实际已被删除），工具会：

1. 记录警告日志，但不会中断整个迁移流程
2. 在迁移结束时提供详细的失败对象报告
3. 当失败对象数量超过10个时，自动创建失败对象列表文件，便于后续处理

### 失败报告

迁移完成后，工具会输出：
- 成功迁移的对象数量和总大小
- 失败的对象数量和按桶分组的失败统计
- 对于数量较多的失败，会创建详细的失败对象列表文件(failed_objects_*_*.txt)

## 示例

### 迁移单个桶

```bash
python main.py --source-endpoint "http://source-s3.example.com" \
               --source-access-key "source_access_key" \
               --source-secret-key "source_secret_key" \
               --target-endpoint "http://target-s3.example.com" \
               --target-access-key "target_access_key" \
               --target-secret-key "target_secret_key" \
               --buckets "my-bucket"
```

### 从Cloudflare R2迁移

```bash
python main.py --source-endpoint "https://<accountid>.r2.cloudflarestorage.com" \
               --source-access-key "R2_ACCESS_KEY" \
               --source-secret-key "R2_SECRET_KEY" \
               --is-source-r2 \
               --target-endpoint "http://target-s3.example.com" \
               --target-access-key "target_access_key" \
               --target-secret-key "target_secret_key" \
               --buckets "my-bucket"
```

### 迁移多个桶

```bash
python main.py --source-endpoint "http://source-s3.example.com" \
               --source-access-key "source_access_key" \
               --source-secret-key "source_secret_key" \
               --target-endpoint "http://target-s3.example.com" \
               --target-access-key "target_access_key" \
               --target-secret-key "target_secret_key" \
               --buckets "bucket1,bucket2,bucket3" \
               --max-workers 20
```

### 使用配置文件并调整默认参数

```bash
# 创建配置文件
cp config.example.ini config.ini
# 编辑 config.ini 设置必要参数
# 运行程序，使用命令行覆盖某些配置
python main.py --config config.ini --max-workers 15
```

## 注意事项

1. 确保有足够的网络带宽支持迁移操作
2. 大文件会自动使用分块上传，小文件使用简单复制
3. 如果目标桶不存在，程序会尝试创建它
4. 程序会自动处理分页列表，支持大量对象的迁移
5. 如需中断迁移过程，可按Ctrl+C，程序会尝试清理未完成的分块上传
6. 敏感信息（如密钥）建议通过配置文件提供，不要直接在命令行参数中指定
7. 如果源对象在迁移过程中发生变化（新增或删除），可能导致统计数据不准确
8. 如果遇到"NoSuchKey"错误，说明对象在源存储库中找不到，但该对象会被跳过，不影响其他文件的迁移
9. 使用Cloudflare R2作为源存储时，请确保启用`--is-source-r2`参数或在配置文件中设置`is_r2 = true` 