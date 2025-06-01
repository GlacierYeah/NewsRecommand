from flask import Flask, jsonify, request, redirect, url_for, session, render_template
from flask_mysqldb import MySQL
from spark_recommend import get_recommendations_for_user, get_content_based_recommendations, \
    get_popularity_based_recommendations
import json

app = Flask(__name__)
app.secret_key = 'your_secret_key'  # 设置会话密钥

# MySQL 配置
app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = '123456'
app.config['MYSQL_DB'] = 'news_recommend'
mysql = MySQL(app)

# 登录页面
@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        username = request.form['username']

        # 验证用户
        cur = mysql.connection.cursor()
        cur.execute("SELECT user_id FROM users WHERE username = %s", (username,))
        user = cur.fetchone()
        cur.close()

        if user:
            session['user_id'] = user[0]  # 将用户ID存入会话
            return redirect(url_for('recommend'))
        else:
            return "登录失败，用户名不存在"
    return render_template('index.html')

# 推荐页面
@app.route('/recommend')
def recommend():
    if 'user_id' not in session:
        return redirect(url_for('index'))
    return render_template('recommend.html')

@app.route('/api/recommend')
def get_recommendations():
    if 'user_id' not in session:
        return jsonify({"error": "未登录"}), 401

    user_id = session['user_id']
    page = int(request.args.get('page', 1))  # 获取当前页数
    per_page = 6  # 每页显示的新闻数量

    # 计算推荐结果（仅在首次加载时）
    collaborative_recommendations = get_recommendations_for_user(user_id)
    content_recommendations = get_content_based_recommendations(user_id)
    popularity_recommendations = get_popularity_based_recommendations(user_id)

    # 合并推荐结果，去重并保证推荐多样性
    recommended_news_ids = list(set(collaborative_recommendations + content_recommendations + popularity_recommendations))

    # 缓存推荐结果（如果是分页请求）
    start_index = (page - 1) * per_page
    end_index = start_index + per_page
    news_to_return = recommended_news_ids[start_index:end_index]

    # 从数据库中获取新闻内容
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT 
            news_id, category, content,
            click_count,
            (SELECT COUNT(*) FROM user_clicks WHERE news_id = n.news_id AND react = 'like') AS like_count,
            (SELECT COUNT(*) FROM user_clicks WHERE news_id = n.news_id AND react = 'hate') AS hate_count,
            EXISTS(SELECT 1 FROM user_clicks WHERE user_id = %s AND news_id = n.news_id AND react = 'like') AS liked,
            EXISTS(SELECT 1 FROM user_clicks WHERE user_id = %s AND news_id = n.news_id AND react = 'hate') AS hated
        FROM news n
        WHERE news_id IN %s
    """, (user_id, user_id, tuple(news_to_return)))
    news_data = cur.fetchall()
    cur.close()

    result = [{
        "news_id": row[0],
        "category": row[1],
        "content": row[2],
        "click_count": row[3],
        "like_count": row[4],
        "hate_count": row[5],
        "liked": row[6],
        "hated": row[7]
    } for row in news_data]

    return jsonify(result)

@app.route('/api/update_reaction/<int:news_id>/<reaction>', methods=['POST'])
def update_reaction(news_id, reaction):
    if 'user_id' not in session:
        return jsonify({"error": "未登录"}), 401

    user_id = session['user_id']

    if reaction not in ['like', 'hate']:
        return jsonify({"error": "无效的反应类型"}), 400

    cur = mysql.connection.cursor()

    try:
        # 根据用户反应类型更新赞/踩
        if reaction == 'like':
            print(f"Updating LIKE reaction for user {user_id} on news {news_id}")  # Debugging line
            cur.execute("""
                INSERT INTO user_clicks (user_id, news_id, react) 
                VALUES (%s, %s, 'like') 
                ON DUPLICATE KEY UPDATE react = 'like';
            """, (user_id, news_id))
        elif reaction == 'hate':
            print(f"Updating HATE reaction for user {user_id} on news {news_id}")  # Debugging line
            cur.execute("""
                INSERT INTO user_clicks (user_id, news_id, react) 
                VALUES (%s, %s, 'hate') 
                ON DUPLICATE KEY UPDATE react = 'hate';
            """, (user_id, news_id))

        # 提交到数据库
        mysql.connection.commit()
        print(f"Commit successful!")  # Debugging line

        # 获取更新后的赞/踩数量
        cur.execute("""
            SELECT 
                (SELECT COUNT(*) FROM user_clicks WHERE news_id = %s AND react = 'like') AS like_count,
                (SELECT COUNT(*) FROM user_clicks WHERE news_id = %s AND react = 'hate') AS hate_count
        """, (news_id, news_id))
        counts = cur.fetchone()

        cur.close()

        return jsonify({
            "like_count": counts[0],
            "hate_count": counts[1]
        })

    except Exception as e:
        mysql.connection.rollback()  # Rollback in case of error
        cur.close()
        return jsonify({"error": f"数据库错误: {str(e)}"}), 500



@app.route('/api/update_click/<int:news_id>', methods=['POST'])
def update_click(news_id):
    if 'user_id' not in session:
        return jsonify({"error": "未登录"}), 401

    user_id = session['user_id']

    cur = mysql.connection.cursor()
    cur.execute("""
        UPDATE news
        SET click_count = click_count + 1
        WHERE news_id = %s
    """, (news_id,))
    mysql.connection.commit()

    cur.execute("""
        SELECT react FROM user_clicks WHERE user_id = %s AND news_id = %s
    """, (user_id, news_id))
    react = cur.fetchone()

    if react is None:
        cur.execute("""
            INSERT INTO user_clicks (user_id, news_id, react)
            VALUES (%s, %s, 'click')
        """, (user_id, news_id))
    elif react[0] == 'none':
        cur.execute("""
            UPDATE user_clicks
            SET react = 'click'
            WHERE user_id = %s AND news_id = %s
        """, (user_id, news_id))

    mysql.connection.commit()

    cur.execute("SELECT click_count FROM news WHERE news_id = %s", (news_id,))
    updated_count = cur.fetchone()[0]

    cur.close()

    return jsonify({"click_count": updated_count})

@app.route('/news_detail/<int:news_id>')
def news_detail(news_id):
    return render_template('news_detail.html')


@app.route('/api/news_detail/<int:news_id>')
def get_news_detail(news_id):
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT 
            news_id, category, content, click_count,
            (SELECT COUNT(*) FROM user_clicks WHERE news_id = %s AND react = 'like') AS like_count,
            (SELECT COUNT(*) FROM user_clicks WHERE news_id = %s AND react = 'hate') AS hate_count,
            EXISTS(SELECT 1 FROM user_clicks WHERE user_id = %s AND news_id = %s AND react = 'like') AS liked,
            EXISTS(SELECT 1 FROM user_clicks WHERE user_id = %s AND news_id = %s AND react = 'hate') AS hated
        FROM news
        WHERE news_id = %s
    """, (news_id, news_id, session.get('user_id'), news_id, session.get('user_id'), news_id, news_id))
    news = cur.fetchone()
    cur.close()

    if news:
        return jsonify({
            "news_id": news[0],
            "category": news[1],
            "content": news[2],
            "click_count": news[3],
            "like_count": news[4],
            "hate_count": news[5],
            "liked": news[6],
            "hated": news[7]
        })
    else:
        return jsonify({"error": "新闻未找到"}), 404






if __name__ == '__main__':
    app.run(debug=False)
