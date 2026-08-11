# 渐进式读书地图

先看全书结构，按问题深挖，最后回到原文。

这里收录我在实际阅读中持续修正的阅读地图。地图用于定位、比较和提出问题，不替代原书。

在线阅读：<https://li-sanze.github.io/reading-maps/>

## 当前书架

- [《如何阅读一本书》](books/how-to-read-a-book/reading.html)：主地图与证据数据。
- [《毛泽东选集》](books/mao-selected-works/reading.html)：主地图、证据数据和按需生成的深挖模块。

## 目录

```text
reading-maps/
├── index.html
└── books/
    ├── how-to-read-a-book/
    │   ├── reading.html
    │   └── reading.json
    └── mao-selected-works/
        ├── reading.html
        ├── reading.json
        └── modules/
```

每本书以 `reading.html + reading.json` 为稳定产物：HTML 负责阅读，JSON 保留结构、来源定位和审计信息。深挖模块只在真实阅读问题出现后增加。

## 公开边界

- 不收录或分发 EPUB、TXT、PDF 等原书文件。
- 不提供原书下载链接。
- 只保留原创结构、评论、图示、必要短引文和来源定位。
- AI 可以协助整理，最终内容需要人工审阅，并回到原文校正。
- 版本、材料或历史解释存在不确定性时，如实保留边界。

## 本地阅读

这是无构建依赖的静态网站，直接用浏览器打开 `index.html` 即可。

## 许可

- 网站代码：[MIT](LICENSE)
- 原创阅读地图文字、原创图示和结构化数据：[CC BY 4.0](CONTENT-LICENSE.md)
- 书名、短引文、第三方资料和商标不纳入以上授权，权利归各自权利人。
