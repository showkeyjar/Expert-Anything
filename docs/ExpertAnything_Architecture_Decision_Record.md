

# ExpertAnything Architecture Decision Record

# ADR-001：系统核心定位决策

## Status

Accepted

## Decision

ExpertAnything 定义为：

> Personal Learning OS，而不是 AI Reader 或 Knowledge Chatbot。

---

## Background

当前大量 AI 知识产品采用：

```
Document
 ↓
Chunk
 ↓
Embedding
 ↓
RAG
 ↓
Chat
```

这种模式解决：

> 信息获取

但无法解决：

- 用户是否理解

- 用户是否掌握

- 用户如何成长

因此 ExpertAnything 不以问答为核心。

---

## Consequence

所有功能必须回答：

> 是否促进用户能力提升？

如果只是：

- 更快搜索

- 更方便总结

- 更漂亮聊天

不是核心价值。

---

---

# ADR-002：核心数据模型决策

## Decision

系统核心对象定义：

```
KnowledgeAsset
```

而不是：

```
Book
Document
PDF
```

---

## Reason

未来知识来源：

```
KnowledgeAsset

├── Book
├── Paper
├── Video
├── Course
├── GitHub Repository
├── Expert Experience
└── Personal Note
```

---

## Data Model

```json
{
  "asset_id": "xxx",

  "type": "book",

  "title": "智能体满级玩家",

  "concepts": [],

  "skills": [],

  "learning_paths": [],

  "agents": []
}
```

---

## Consequence

书籍只是插件。

系统不会被 EPUB 限制。

---

# ADR-003：知识表示决策

## Decision

采用：

Hybrid Knowledge Architecture

即：

```
Vector Knowledge

+

Graph Knowledge

+

Structured Knowledge
```

---

## Why not pure RAG?

RAG 擅长：

找到相关内容。

但是不知道：

- 概念关系

- 学习顺序

- 前置知识

---

## Architecture

```
                 Knowledge Asset


                        |

              Knowledge Extraction


                        |

        --------------------------------

        |              |              |

    Vector DB     Knowledge Graph   Schema


        |              |              |


        --------------------------------


                 Knowledge Runtime
```

---

# ADR-004：Agent架构决策

## Decision

采用：

Multi-Agent Learning Architecture

不是：

一个万能 Agent。

---

## Agent Roles

```
                Learning Agent


                     |

 ---------------------------------

 |          |          |          |

Teacher   Coach   Reviewer   Visualizer


                     |

                Librarian
```

---

# Agent职责边界

## Teacher Agent

负责：

- 解释

- 举例

- 迁移

禁止：

- 修改知识库

---

## Librarian Agent

负责：

- 文档解析

- 知识整理

禁止：

- 教学

---

## Reviewer Agent

负责：

- 判断掌握程度

- 生成评价

---

## Visualization Agent

负责：

- 图表

- 图片

- 动画

---

# ADR-005：学习闭环决策

## Decision

所有学习过程必须形成：

Learning Loop

```
理解

 ↓

练习

 ↓

反馈

 ↓

修正

 ↓

能力提升
```

---

## Example

用户学习：

Agent Memory

系统：

### Explanation

解释 Memory。

↓

### Visualization

生成架构图。

↓

### Practice

设计 Memory。

↓

### Review

评分。

↓

### Update Learner Model

---

# ADR-006：用户模型决策

## Decision

建立：

Learner Model

它是系统核心资产。

---

## Example

```json
{
"user":"showkey",

"skills":{

"Agent Design":0.8,

"Memory":0.4,

"Multi Agent":0.3

},

"learning_style":

"visual",

"weakness":

[
"task decomposition"
]

}
```

---

## Purpose

未来 AI 不只是知道：

“知识是什么”。

还知道：

“用户缺什么”。

---

# ADR-007：多模态学习决策

## Decision

知识表达不限定文本。

系统应该主动选择：

最佳表达方式。

---

## Example

概念：

Transformer Attention

输出：

文本：

解释机制。

图：

Attention Matrix。

动画：

Token Flow。

代码：

PyTorch Demo。

---

# ADR-008：技术栈原则

## Runtime

推荐：

LangGraph

原因：

需要：

- 状态

- 长任务

- 多Agent

- Human in Loop

---

## Backend

推荐：

Python + FastAPI

---

## Knowledge Layer

Vector:

Qdrant

Graph:

Neo4j

Database:

PostgreSQL

---

## Frontend

Next.js

---

# ADR-009：MVP范围控制

## Version 0.1

目标：

一本书成为一个智能导师。

---

功能：

```
上传 EPUB

↓

知识解析

↓

知识地图

↓

Book Agent

↓

互动学习

↓

生成图表

↓

生成练习

↓

学习记录
```

---

禁止：

第一版做：

- 社区

- 市场

- 商城

- 全自动课程生成

- 通用Agent平台

---

# ADR-010：未来评价指标

错误指标：

```
DAU
聊天次数
Token消耗
```

---

核心指标：

```
Learning Gain

学习增益
```

例如：

学习前：

Agent设计能力：

40%

学习后：

75%

---

# 最终架构愿景

```
                  ExpertAnything


                         |

              Personal Learning OS


                         |

 -------------------------------------------------

 |                    |                           |

Knowledge           Learner                  Agent

System              Model                    System


                         |

                  Human Capability


                         |

                    Expertise
```

---

## 最重要的一条架构原则

> 不要构建一个会回答问题的 AI。
>
> 构建一个能够帮助人类形成专家能力的 AI 系统。


