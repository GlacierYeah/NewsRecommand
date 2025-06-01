from pyspark.sql import SparkSession
import os
import re

# 初始化Spark会话
spark = SparkSession.builder.appName("StoreFullTextToDB").getOrCreate()

# 定义读取文件的函数，支持多种编码
def read_file_with_fallback_encoding(file_path):
    encodings = ["utf-8", "gbk", "latin1", "gb18030", "big5"]
    for encoding in encodings:
        try:
            with open(file_path, "r", encoding=encoding) as file:
                content = file.read()
                # 截断内容，确保不超过 LONGTEXT 类型的最大长度
                return content[:4294967295]  # LONGTEXT 最大长度为 4 GB
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError(f"Failed to decode file: {file_path} with encodings: {encodings}")

# 去掉分类名称中的数字
def clean_category_name(category):
    # 使用正则表达式去掉数字部分
    return re.sub(r"\d+", "", category)

# 读取并处理所有文本文件
base_path = "D:/code/PySparkProject/data/文本分类语料库"
categories = ["交通214", "体育450", "军事249", "医药204", "政治505", "教育220", "环境200", "经济325", "艺术248"]

# 初始化一个空列表，用于存储所有新闻数据
all_news_data = []

# 遍历每个分类文件夹
for category in categories:
    category_path = os.path.join(base_path, category)
    # 去掉分类名称中的数字
    clean_category = clean_category_name(category)
    # 遍历文件夹中的每个文件
    for file_name in os.listdir(category_path):
        file_path = os.path.join(category_path, file_name)
        try:
            # 读取文件的全部内容
            content = read_file_with_fallback_encoding(file_path)
            # 将内容和分类添加到列表中
            all_news_data.append({
                "content": content,
                "category": clean_category
            })
        except Exception as e:
            print(f"Error processing file: {file_path}, error: {e}")

# 将数据转换为Spark DataFrame
df = spark.createDataFrame(all_news_data)

# 查看处理后的数据
print("处理后的数据：")
df.show(truncate=False)

# 存储到数据库
db_url = "jdbc:mysql://localhost:3306/news_recommend"
db_properties = {
    "user": "root",  # 确保用户名正确
    "password": "123456",  # 确保密码正确
    "driver": "com.mysql.cj.jdbc.Driver"
}

# 存储到数据库（不包含 id 字段，让数据库自动生成）
df.select("content", "category").write.jdbc(
    db_url, "news", mode="append", properties=db_properties
)

# 关闭Spark会话
spark.stop()
