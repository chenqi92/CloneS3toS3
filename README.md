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
- 支持直接读取模式，解决分块读取可能引起的问题

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

如果需要直接读取文件而不使用分块方式，添加`--direct-read`参数：

```bash
python main.py --source-endpoint SOURCE_S3_URL \
               --source-access-key SOURCE_ACCESS_KEY \
               --source-secret-key SOURCE_SECRET_KEY \
               --target-endpoint TARGET_S3_URL \
               --target-access-key TARGET_ACCESS_KEY \
               --target-secret-key TARGET_SECRET_KEY \
               --buckets "my-bucket" \
               --direct-read
```

### 2. 使用配置文件

创建一个配置文件，例如 `config.ini`（可以参考 `config.example.ini` 创建）:

```ini
[source]
endpoint = http://source-s3.example.com
access_key = source_access_key
secret_key = source_secret_key
is_r2 = false  # 设置为true表示源存储为Cloudflare R2
direct_read = true  # 设置为true表示直接读取文件而不使用分块方式
max_direct_size = 524288000  # 直接读取的最大文件大小，超过此大小使用分块上传 (默认: 500MB)

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
python main.py --config config.ini --max-workers 20 --direct-read
```

## 参数说明

| 参数 | 说明 | 是否必填 |
|------|------|---------|
| `--config` | 配置文件路径 | 否 |
| `--source-endpoint` | 源S3端点URL | 是* |
| `--source-access-key` | 源S3访问密钥 | 是* |
| `--source-secret-key` | 源S3秘密密钥 | 是* |
| `--is-source-r2` | 源存储是否为Cloudflare R2 | 否 |
| `--direct-read` | 是否直接读取文件而不使用分块方式 | 否 |
| `--max-direct-size` | 直接读取的最大文件大小，超过此大小使用分块上传 (默认: 500MB) | 否 |
| `--target-endpoint` | 目标S3端点URL | 是* |
| `--target-access-key` | 目标S3访问密钥 | 是* |
| `--target-secret-key` | 目标S3秘密密钥 | 是* |
| `--buckets` | 要迁移的桶名列表，用逗号分隔 | 是* |
| `--max-workers` | 最大工作线程数 (默认: 10) | 否 |
| `--chunk-size` | 分块上传大小，单位字节 (默认: 8MB) | 否 |

(*) 如果使用配置文件，这些参数可以在配置文件中指定

## 文件读取方式

本工具提供了两种读取文件的方式：

### 1. 直接读取模式

当启用直接读取模式时(`--direct-read`或在配置文件中设置`direct_read = true`)，工具会尝试一次性读取整个文件内容并上传，这对于以下情况特别有用：

- 源存储对Range请求支持不完善（如某些特殊的S3兼容存储）
- 遇到了"NoSuchKey"或其他与分块读取相关的错误
- 主要迁移的是小文件

注意：对于超过`max_direct_size`设置的大文件（默认500MB），即使在直接读取模式下也会使用分块上传以避免内存溢出。

### 2. 分块读取模式（默认）

分块读取模式会将大文件分成多个块进行读取和上传，适用于：

- 迁移大量大文件时节省内存
- 源存储支持Range请求
- 需要在上传过程中显示详细进度

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

### 使用直接读取模式迁移

适用于遇到"NoSuchKey"错误时：

```bash
python main.py --source-endpoint "http://source-s3.example.com" \
               --source-access-key "source_access_key" \
               --source-secret-key "source_secret_key" \
               --target-endpoint "http://target-s3.example.com" \
               --target-access-key "target_access_key" \
               --target-secret-key "target_secret_key" \
               --buckets "my-bucket" \
               --direct-read
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
10. 如果遇到"NoSuchKey"错误且确定文件存在，请尝试使用直接读取模式(`--direct-read`)
11. 注意内存使用：直接读取大文件可能导致内存消耗较高，请根据服务器配置适当调整`max_direct_size` 

## 辅助脚本

本工具包括以下辅助脚本，帮助您更容易地使用和测试迁移功能：

### 1. 配置文件编码修复工具

如果您在Windows系统上遇到配置文件编码问题（例如UnicodeDecodeError），请使用以下脚本将配置文件转换为UTF-8编码：

```bash
python fix_encoding.py --config config.ini --backup
```

参数说明：
- `--config`: 指定配置文件路径（默认为"config.ini"）
- `--backup`: 创建原始文件的备份（可选）

### 2. 连接测试工具

在执行迁移前测试源存储和目标存储的连接状态：

```bash
python test_connection.py --config config.ini
```

参数说明：
- `--config`: 指定配置文件路径（默认为"config.ini"）
- `--buckets`: 指定要测试的存储桶，逗号分隔（可选，默认使用配置文件中的值）
- `--source-only`: 仅测试源存储连接
- `--target-only`: 仅测试目标存储连接

### 3. 迁移示例脚本

提供了一个简单的迁移示例脚本，展示如何在Python代码中使用CloneS3类进行自定义迁移：

```bash
python migrate_example.py
```

修改脚本中的配置参数以适应您的环境，可以作为编写自定义迁移脚本的参考。

### 4. 标准UTF-8配置模板

使用标准UTF-8编码的配置文件模板，避免编码问题：

```bash
cp config.example.ini config.ini
# 然后编辑config.ini文件填入您的配置
```

## 常见问题

### 1. Windows下的编码问题

问题：运行时出现"UnicodeDecodeError: 'gbk' codec can't decode byte..."错误

解决方法：
1. 使用`fix_encoding.py`工具将配置文件转换为UTF-8编码
2. 或者从`config.template.ini`创建配置文件，确保使用UTF-8编码

### 2. 连接失败问题

问题：无法连接到源或目标存储

解决方法：
1. 使用`test_connection.py`脚本测试连接
2. 检查端点URL是否正确（包括http/https前缀）
3. 验证访问密钥和秘密密钥是否有效
4. 确认存储桶名称是否正确拼写

### 3. NoSuchKey错误

问题：迁移过程中出现"NoSuchKey"错误

解决方法：
1. 启用直接读取模式(`--direct-read`)
2. 如果使用Cloudflare R2作为源，确保设置了`--is-source-r2`选项
3. 使用`test_connection.py`验证对象是否真实存在于源存储中

### 4. 内存使用过高

问题：处理大文件时内存使用过高

解决方法：
1. 调整`max_direct_size`参数限制直接读取的文件大小
2. 减少`max_workers`参数值，限制并发线程数量
3. 确保服务器有足够的RAM和SWAP空间 

## 效果展示
![](https://upload.fffuk.com/cloudpic/ai/2025/04/70d1abe942c95190ab0862a677ba4da7.png)