<div align="center">

# 渐进式读书地图

**用 AI 帮你更快回到原文，而不是替你读书。**

先建立全书结构，再按真实问题深挖。

[**在线阅读**](https://li-sanze.github.io/reading-maps/)

</div>

[![渐进式读书地图首页：书籍主地图与阅读路径](assets/site-preview.png)](https://li-sanze.github.io/reading-maps/)

## 当前书架

- **《如何阅读一本书》** — [打开主地图](https://li-sanze.github.io/reading-maps/books/%E5%A6%82%E4%BD%95%E9%98%85%E8%AF%BB%E4%B8%80%E6%9C%AC%E4%B9%A6/reading.html)：四层阅读、四个主动问题与阅读判断。
- **《毛泽东选集》** — [打开主地图与深挖](https://li-sanze.github.io/reading-maps/books/%E6%AF%9B%E6%B3%BD%E4%B8%9C%E9%80%89%E9%9B%86/reading.html)：时期、问题、方法与按需生成的深挖模块。
- **《乌合之众》** — [打开主地图](https://li-sanze.github.io/reading-maps/books/%E4%B9%8C%E5%90%88%E4%B9%8B%E4%BC%97/reading.html)：群体形成、信念传播、领袖说服与现代批判校正。
- **《月亮与六便士》** — [打开分层剧透地图](https://li-sanze.github.io/reading-maps/books/%E6%9C%88%E4%BA%AE%E4%B8%8E%E5%85%AD%E4%BE%BF%E5%A3%AB/reading.html)：分层剧透、五段叙事、叙述证据与艺术/责任审计。
- **《置身事内》** — [打开主地图](https://li-sanze.github.io/reading-maps/books/%E7%BD%AE%E8%BA%AB%E4%BA%8B%E5%86%85/reading.html)：2021 年上海人民出版社；地方政府的财税、土地与投融资，以及作者怎样把这些机制接到城市化、债务和内外失衡。
- **《阿加莎·克里斯蒂侦探小说大全集（全85册）》** — [打开主地图](https://li-sanze.github.io/reading-maps/books/%E9%98%BF%E5%8A%A0%E8%8E%8E%C2%B7%E5%85%8B%E9%87%8C%E6%96%AF%E8%92%82%E4%BE%A6%E6%8E%A2%E5%B0%8F%E8%AF%B4%E5%A4%A7%E5%85%A8%E9%9B%86%EF%BC%88%E5%85%A885%E5%86%8C%EF%BC%89/reading.html)：新星出版社中文合订本；85 个作品级条目含长篇、合集、戏剧小说化、续写与自传。默认无剧透，深挖按需生成。

## 地图怎么用

1. **建立结构**：先判断全书讨论什么、怎样展开，以及版本和材料边界。
2. **按问题深挖**：只有真实疑问出现时，才进入主题、篇章或外部背景。
3. **回到原文**：地图负责定位、比较和校正，不替代作者的完整论证与语境。

每本书以 `reading.html + reading.json` 为稳定产物：HTML 用于阅读，JSON 保留结构、来源定位和审计信息。深挖模块只在真实阅读问题出现后增加。

## 生成与审计

仓库内置 [`read-book`](skills/read-book/SKILL.md) Skill，支持从中文 TXT、Markdown 和 EPUB 建立全书主地图、按真实问题深挖，以及最小修订现有地图。

## 内容边界

- 不收录或分发 EPUB、TXT、PDF 等原书文件，也不提供原书下载链接。
- 只公开原创结构、评论、图示、必要短引文和来源定位。
- AI 可以协助整理；发布内容需要人工审阅，并回到原文校正。
- 版本、材料或历史解释存在不确定性时，如实保留边界。

## 本地阅读

网站没有构建依赖，克隆仓库后直接用浏览器打开 `index.html` 即可。

## 许可

- 网站代码：[MIT](LICENSE)
- 原创阅读地图文字、原创图示和结构化数据：[CC BY 4.0](CONTENT-LICENSE.md)
- 书名、短引文、第三方资料和商标不纳入以上授权，权利归各自权利人。
