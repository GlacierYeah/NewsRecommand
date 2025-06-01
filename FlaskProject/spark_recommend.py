from pyspark.sql import SparkSession
from pyspark.ml.recommendation import ALS
from pyspark.ml.feature import HashingTF, IDF, Tokenizer
from pyspark.sql import functions as F
from pyspark.ml.linalg import DenseVector
from pyspark.ml.feature import Word2Vec
from pyspark.sql.types import DoubleType, ArrayType
from pyspark.ml.linalg import Vectors, VectorUDT
from pyspark.ml.feature import VectorAssembler

def get_weighted_rating(react):
    if react == 'like':
        return 1.0
    elif react == 'hate':
        return -1.0
    elif react == 'click':
        return 0.5
    else:
        return 0

def get_popularity_based_recommendations(user_id):
    spark = SparkSession.builder \
        .appName("NewsRecommendationSystem") \
        .getOrCreate()

    try:
        user_clicks_df = spark.read.jdbc("jdbc:mysql://localhost:3306/news_recommend", "user_clicks", properties={
            "user": "root", "password": "123456", "driver": "com.mysql.cj.jdbc.Driver"})

        user_history_df = user_clicks_df.filter(F.col("user_id") == user_id)
        user_history_news_ids = user_history_df.select("news_id").distinct().rdd.flatMap(lambda x: x).collect()

        news_df = spark.read.jdbc("jdbc:mysql://localhost:3306/news_recommend", "news", properties={
            "user": "root", "password": "123456", "driver": "com.mysql.cj.jdbc.Driver"})

        popularity_df = news_df.withColumn(
            "popularity_score", F.col("click_count") * 0.5 + F.col("like_count") * 0.5)

        popular_news = popularity_df.orderBy(F.desc("popularity_score")).limit(50)
        popular_news_ids = popular_news.select("news_id").rdd.flatMap(lambda x: x).collect()

        filtered_popular_news_ids = [news_id for news_id in popular_news_ids if news_id not in user_history_news_ids]

        return filtered_popular_news_ids

    finally:
        spark.stop()

# 创建 UDF
def extract_values(feature):
    return feature.values.tolist() if feature is not None else []

extract_values_udf = F.udf(extract_values, ArrayType(DoubleType()))

def convert_to_vector(array):
    return Vectors.dense(array)

convert_to_vector_udf = F.udf(convert_to_vector, VectorUDT())

def get_recommendations_for_user(user_id):
    spark = SparkSession.builder \
        .appName("NewsRecommendationSystem") \
        .getOrCreate()

    jdbc_url = "jdbc:mysql://localhost:3306/news_recommend"
    connection_properties = {
        "user": "root",
        "password": "123456",
        "driver": "com.mysql.cj.jdbc.Driver"
    }

    user_clicks_df = spark.read.jdbc(jdbc_url, "user_clicks", properties=connection_properties)

    user_history_df = user_clicks_df.filter(F.col("user_id") == user_id)
    user_history_news_ids = user_history_df.select("news_id").distinct().rdd.flatMap(lambda x: x).collect()

    ratings_df = user_clicks_df.withColumn(
        "rating", F.udf(get_weighted_rating)(F.col("react"))
    )
    ratings_df = ratings_df.withColumn("rating", ratings_df["rating"].cast("float"))

    als = ALS(
        maxIter=10,
        regParam=0.1,
        userCol="user_id",
        itemCol="news_id",
        ratingCol="rating",
        coldStartStrategy="drop",
    )

    model = als.fit(ratings_df)

    user_recommendations = model.recommendForAllUsers(10)
    user_recommendations = user_recommendations.filter(F.col("user_id") == user_id)

    recommendations = user_recommendations \
        .withColumn("recommendation", F.explode("recommendations")) \
        .select(F.col("recommendation.news_id").alias("news_id")) \
        .collect()

    recommended_news_ids = [row.news_id for row in recommendations if row.news_id not in user_history_news_ids]

    spark.stop()

    return recommended_news_ids

def get_content_based_recommendations(user_id):
    spark = SparkSession.builder \
        .appName("NewsRecommendationSystem") \
        .getOrCreate()

    try:
        user_clicks_df = spark.read.jdbc("jdbc:mysql://localhost:3306/news_recommend", "user_clicks", properties={
            "user": "root", "password": "123456", "driver": "com.mysql.cj.jdbc.Driver"})

        user_history_df = user_clicks_df.filter(F.col("user_id") == user_id)

        user_history_with_category = user_history_df.join(
            spark.read.jdbc("jdbc:mysql://localhost:3306/news_recommend", "news", properties={
                "user": "root", "password": "123456", "driver": "com.mysql.cj.jdbc.Driver"}),
            on="news_id", how="inner").select(
            F.col("news_id"),
            F.col("category").alias("category_user_history")
        )

        news_df = spark.read.jdbc("jdbc:mysql://localhost:3306/news_recommend", "news", properties={
            "user": "root", "password": "123456", "driver": "com.mysql.cj.jdbc.Driver"})

        user_history_news_ids = user_history_df.select("news_id").distinct().rdd.flatMap(lambda x: x).collect()

        tokenizer = Tokenizer(inputCol="content", outputCol="words")
        words_data = tokenizer.transform(news_df)

        hashingTF = HashingTF(inputCol="words", outputCol="raw_features", numFeatures=1000)
        featurized_data = hashingTF.transform(words_data)

        idf = IDF(inputCol="raw_features", outputCol="features")
        idf_model = idf.fit(featurized_data)
        rescaled_data = idf_model.transform(featurized_data)

        news_with_features = rescaled_data.select("news_id", "category", "features")

        user_history_with_features = user_history_with_category.join(news_with_features, on="news_id", how="inner") \
            .select(
            F.col("news_id"),
            F.col("category").alias("category_news"),
            "features"
        )

        user_history_with_values = user_history_with_features.withColumn(
            "feature_values", extract_values_udf(F.col("features"))
        )

        user_history_with_values = user_history_with_values.withColumn(
            "feature_vector", convert_to_vector_udf(F.col("feature_values"))
        )

        assembler = VectorAssembler(inputCols=["feature_vector"], outputCol="feature_vector_assembled")
        user_history_with_vectors = assembler.transform(user_history_with_values)

        recommendations = [row.news_id for row in user_history_with_vectors.collect() if row.news_id not in user_history_news_ids]

        return recommendations

    finally:
        spark.stop()
