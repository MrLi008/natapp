# natapp
python tornado mongodb 可缓存版-内网转外网访问工具
# 使用方式
1. conf.txt 为配置文件
port为对外开放端口
url_base 为部署到外网的访问地址,供内网服务请求和转发数据
url_target 为内网转发访问的原网址. 格式为http[s]://[IP]:[Port]/
2. 默认mongodb 数据库
2. 外网访问启动service.py
3. 内网启动consumer.py
4. 程序默认包含了一个半自动化的爬虫效果.有兴趣可以交流交流
