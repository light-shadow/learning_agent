import { type ChangeEvent, type ReactElement, useCallback, useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";

import "./styles.css";

type Source = { source_id: string; title: string; source_type: string; created_at?: string; chunk_count?: number };
type Concept = { concept_id: string; title: string; summary: string; source_refs?: string[] };
type Question = { question_id: string; question_type: string; prompt: string; options: string[]; concept_title?: string; source_refs?: string[] };
type ReviewItem = { concept_id: string; title: string; summary: string; mastery: number; last_answered_at?: string | null };
type AttemptHistory = { attempt_id: string; question_id: string; question_type: string; prompt: string; answer: string; score: number | null; status: "correct" | "incorrect"; feedback: string; created_at: string; concept_title: string };
type Result = { message?: string; feedback?: string; score?: number; status?: string; mastery?: number; [key: string]: unknown };

/** 请求本地 API，并将错误响应统一转换为可读文本。 */
async function api<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, options);
  const body = await response.json().catch(() => ({ message: "服务返回了无法解析的结果。" })) as Result;
  if (!response.ok) {
    throw new Error(body.message ?? "请求失败。");
  }
  return body as T;
}

/** 以本地时间显示资料创建时间。 */
function formatTime(value?: string): string {
  return value ? new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)) : "刚刚导入";
}

/** 将测验题型转换为中文标签。 */
function questionTypeLabel(questionType: string): string {
  return ({ single_choice: "单选题", true_false: "判断题", short_answer: "简答题" } as Record<string, string>)[questionType] ?? questionType;
}

/** 将掌握度转换为 0 到 100 的安全百分比。 */
function masteryPercent(mastery: number): number {
  return Math.round(Math.max(0, Math.min(1, mastery)) * 100);
}

/** 根据掌握度与作答记录给出可读的复习状态。 */
function reviewStatus(item: ReviewItem): { label: string; tone: "urgent" | "warning" | "good" | "new" } {
  if (!item.last_answered_at) return { label: "待诊断", tone: "new" };
  if (item.mastery < 0.4) return { label: "优先复习", tone: "urgent" };
  if (item.mastery < 0.7) return { label: "需要巩固", tone: "warning" };
  return { label: "掌握良好", tone: "good" };
}

/** 计算当前复习清单中的薄弱与未作答知识点数量。 */
function reviewOverview(items: ReviewItem[]): { weak: number; untested: number } {
  return {
    weak: items.filter((item) => item.last_answered_at && item.mastery < 0.7).length,
    untested: items.filter((item) => !item.last_answered_at).length,
  };
}

/** 将作答结果转换为用户可读的状态标签。 */
function attemptStatusLabel(status: AttemptHistory["status"]): string {
  return status === "correct" ? "回答正确" : "需要复习";
}

/** 渲染自学 Agent 的资料、测验和复习工作台。 */
function App(): ReactElement {
  const [sources, setSources] = useState<Source[]>([]);
  const [selectedSourceId, setSelectedSourceId] = useState("");
  const [concepts, setConcepts] = useState<Concept[]>([]);
  const [questions, setQuestions] = useState<Question[]>([]);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [learnerId, setLearnerId] = useState("default");
  const [quizCount, setQuizCount] = useState("10");
  const [review, setReview] = useState<ReviewItem[] | null>(null);
  const [history, setHistory] = useState<AttemptHistory[] | null>(null);
  const [notice, setNotice] = useState("准备好开始学习。");
  const [busy, setBusy] = useState(false);

  /** 刷新资料列表，并保留仍有效的当前选择。 */
  const loadSources = useCallback(async (): Promise<void> => {
    const loaded = await api<Source[]>("/api/sources");
    setSources(loaded);
    setSelectedSourceId((current) => current || loaded[0]?.source_id || "");
  }, []);

  useEffect(() => {
    loadSources().catch((error: Error) => setNotice(error.message));
  }, [loadSources]);

  /** 切换资料时只读取已保存的知识点，不触发模型重新提炼。 */
  useEffect(() => {
    let cancelled = false;
    if (!selectedSourceId) {
      setConcepts([]);
      return () => { cancelled = true; };
    }
    api<Concept[]>(`/api/sources/${encodeURIComponent(selectedSourceId)}/concepts`)
      .then((loaded) => { if (!cancelled) setConcepts(loaded); })
      .catch((error: Error) => { if (!cancelled) setNotice(error.message); });
    return () => { cancelled = true; };
  }, [selectedSourceId]);

  /** 选择资料或切换学习者时，自动读取该 PDF 已保存的答题记录。 */
  useEffect(() => {
    let cancelled = false;
    if (!selectedSourceId) {
      setHistory(null);
      return () => { cancelled = true; };
    }
    api<AttemptHistory[]>(`/api/sources/${encodeURIComponent(selectedSourceId)}/history?learnerId=${encodeURIComponent(learnerId)}`)
      .then((loaded) => { if (!cancelled) setHistory(loaded); })
      .catch((error: Error) => { if (!cancelled) setNotice(error.message); });
    return () => { cancelled = true; };
  }, [learnerId, selectedSourceId]);

  /** 包装异步操作，统一显示加载和错误状态。 */
  const perform = useCallback(async (action: () => Promise<void>): Promise<void> => {
    setBusy(true);
    try {
      await action();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "操作失败。");
    } finally {
      setBusy(false);
    }
  }, []);

  /** 切换当前资料时清空前一份 PDF 的临时页面状态。 */
  const selectSource = (sourceId: string): void => {
    setSelectedSourceId(sourceId);
    setConcepts([]);
    setHistory(null);
    setQuestions([]);
    setAnswers({});
  };

  /** 上传本地资料并在成功后刷新列表。 */
  const importFile = async (event: ChangeEvent<HTMLInputElement>): Promise<void> => {
    const file = event.target.files?.[0];
    if (!file) return;
    await perform(async () => {
      const form = new FormData();
      form.append("file", file);
      const result = await api<Result>("/api/sources/file", { method: "POST", body: form });
      const sourceId = String((result.content as Result | undefined)?.source_id ?? "");
      await loadSources();
      selectSource(sourceId);
      setNotice(`已导入：${file.name}`);
    });
    event.target.value = "";
  };

  /** 调用模型从当前 PDF 原文块重新提炼知识点，再读取提炼结果。 */
  const extractConcepts = async (): Promise<void> => {
    if (!selectedSourceId) return;
    await perform(async () => {
      await api<Result>(`/api/sources/${encodeURIComponent(selectedSourceId)}/concepts/extract`, { method: "POST" });
      setConcepts(await api<Concept[]>(`/api/sources/${encodeURIComponent(selectedSourceId)}/concepts`));
      setNotice("AI 已根据 PDF 原文重新提炼知识点。关联题目和学习记录已重建。");
    });
  };

  /** 从当前资料提炼知识点并生成题目。 */
  const generate = async (): Promise<void> => {
    if (!selectedSourceId) return;
    await perform(async () => {
      await api<Result>(`/api/sources/${encodeURIComponent(selectedSourceId)}/generate`, { method: "POST" });
      setConcepts(await api<Concept[]>(`/api/sources/${encodeURIComponent(selectedSourceId)}/concepts`));
      setNotice("知识点和题目已生成。");
    });
  };

  /** 获取测验题目；传入资料 ID 时仅在该资料范围内出题。 */
  const loadQuiz = async (sourceId?: string): Promise<void> => {
    const query = new URLSearchParams({ learnerId, count: quizCount });
    if (sourceId) query.set("sourceId", sourceId);
    const loaded = await api<Question[]>(`/api/quiz?${query.toString()}`);
    setQuestions(loaded);
    setAnswers({});
    setNotice(loaded.length ? "已生成本轮测验。" : "暂无题目，请先生成题目。");
  };

  /** 根据当前选中资料与学习者状态获取下一轮测验。 */
  const startQuiz = async (): Promise<void> => {
    await perform(() => loadQuiz(selectedSourceId || undefined));
  };

  /** 按全部资料中的薄弱知识点优先生成复习测验。 */
  const startReviewQuiz = async (): Promise<void> => {
    await perform(() => loadQuiz());
  };

  /** 获取当前选中 PDF 下该学习者已经提交的答题记录。 */
  const loadHistory = async (): Promise<void> => {
    if (!selectedSourceId) return;
    await perform(async () => {
      const loaded = await api<AttemptHistory[]>(`/api/sources/${encodeURIComponent(selectedSourceId)}/history?learnerId=${encodeURIComponent(learnerId)}`);
      setHistory(loaded);
      setNotice(loaded.length ? "已加载当前 PDF 的答题记录。" : "当前 PDF 暂无答题记录。");
    });
  };

  /** 提交一道题目答案，并移除已完成题目。 */
  const submitAnswer = async (question: Question): Promise<void> => {
    const answer = answers[question.question_id]?.trim();
    if (!answer) {
      setNotice("请先填写答案。");
      return;
    }
    await perform(async () => {
      const result = await api<Result>("/api/quiz/answer", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ learnerId, questionId: question.question_id, answer }) });
      setQuestions((current) => current.filter((item) => item.question_id !== question.question_id));
      if (selectedSourceId) {
        setHistory(await api<AttemptHistory[]>(`/api/sources/${encodeURIComponent(selectedSourceId)}/history?learnerId=${encodeURIComponent(learnerId)}`));
      }
      setNotice(`${result.status === "correct" ? "回答正确" : "已提交"}：${result.feedback ?? "请查看掌握度变化。"}`);
    });
  };

  /** 获取当前学习者的掌握度与复习排序。 */
  const loadReview = async (): Promise<void> => {
    await perform(async () => {
      setReview(await api<ReviewItem[]>(`/api/review?learnerId=${encodeURIComponent(learnerId)}`));
      setNotice("复习建议已更新。");
    });
  };

  const selectedSource = useMemo(() => sources.find((source) => source.source_id === selectedSourceId), [sources, selectedSourceId]);
  const reviewSummary = useMemo(() => review ? reviewOverview(review) : null, [review]);

  return (
    <main className="app-shell">
      <header className="hero">
        <div><p className="eyebrow">AI AGENT DESIGN LEARNING</p><h1>自学 Agent</h1><p>导入 AI Agent 课程 PDF，提炼架构思想并检验掌握情况。</p></div>
        <label className="learner">学习者 <input value={learnerId} onChange={(event) => setLearnerId(event.target.value)} maxLength={64} /></label>
      </header>

      <p className="notice" role="status">{busy ? "正在处理，请稍候…" : notice}</p>

      <section className="dashboard">
        <section className="workspace">
          <div className="panel focus-panel">
            <div className="focus-details">
              <p className="eyebrow">当前学习资料</p>
              <h2>{selectedSource?.title ?? "请选择或上传 PDF"}</h2>
              {selectedSource ? <div className="source-meta"><span>PDF</span><span>{selectedSource.chunk_count ?? 0} 个文本块</span><span>导入于 {formatTime(selectedSource.created_at)}</span></div> : <p className="muted">上传一份 AI Agent 课程 PDF，即可开始提炼与测验。</p>}
              <div className="source-management">
                <label className="source-selector"><span>已导入资料 <em>{sources.length}</em></span><select value={selectedSourceId} onChange={(event) => selectSource(event.target.value)} disabled={!sources.length || busy}><option value="">请选择 PDF</option>{sources.map((source) => <option key={source.source_id} value={source.source_id}>{source.title}</option>)}</select></label>
                <label className="upload compact-upload"><input type="file" accept="application/pdf,.pdf" onChange={importFile} disabled={busy} /><span>上传 PDF</span></label>
                <button className="refresh-sources" onClick={() => perform(loadSources)} disabled={busy}>刷新资料</button>
              </div>
            </div>
            <div className="actions"><button className="secondary" onClick={extractConcepts} disabled={!selectedSourceId || busy}>{concepts.length ? "AI 重新提炼知识点" : "AI 提炼知识点"}</button><button onClick={generate} disabled={!selectedSourceId || busy}>{history?.length ? "重新生成题目" : "生成题目"}</button><label className="quiz-count">本轮题数<select value={quizCount} onChange={(event) => setQuizCount(event.target.value)} disabled={busy}><option value="5">5 题</option><option value="10">10 题</option><option value="15">15 题</option><option value="20">20 题</option></select></label><button className="accent" onClick={startQuiz} disabled={busy}>开始测验</button></div>
          </div>

          <div className="two-columns">
            <section className="panel"><div className="panel-title"><h2>知识脉络</h2><span>{concepts.length} 个知识点</span></div>{concepts.length ? <div className="concept-list">{concepts.map((concept) => <article key={concept.concept_id} className="concept"><h3>{concept.title}</h3><p>{concept.summary}</p><small>{concept.source_refs?.join(" · ")}</small></article>)}</div> : <p className="empty">选择资料后查看或生成知识点。</p>}</section>
            <section className="panel review-panel">
              <div className="panel-title"><div><h2>复习建议</h2><p className="panel-hint">按掌握度、最近作答和未覆盖知识点排序</p></div><button onClick={() => perform(loadReview)} disabled={busy}>更新建议</button></div>
              {review?.length ? <>
                <div className="review-overview" aria-label="复习概览">
                  <div><strong>{review.length}</strong><span>知识点</span></div>
                  <div><strong>{reviewSummary?.weak ?? 0}</strong><span>需要巩固</span></div>
                  <div><strong>{reviewSummary?.untested ?? 0}</strong><span>尚未作答</span></div>
                </div>
                <div className="review-list">
                  {review.map((item, index) => {
                    const status = reviewStatus(item);
                    const percent = masteryPercent(item.mastery);
                    return <article className="review-card" key={item.concept_id}>
                      <div className="review-card-head"><span className="priority">优先级 {index + 1}</span><span className={`status ${status.tone}`}>{status.label}</span></div>
                      <h3>{item.title}</h3>
                      <p>{item.summary}</p>
                      <div className="mastery-row"><span>掌握度</span><strong>{item.last_answered_at ? `${percent}%` : "未测"}</strong></div>
                      <div className={`mastery-bar ${status.tone}`} role="progressbar" aria-label={`${item.title}掌握度`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent}><i style={{ width: `${percent}%` }} /></div>
                      <footer><small>{item.last_answered_at ? `最近作答：${formatTime(item.last_answered_at)}` : "尚未通过题目诊断，建议优先测验。"}</small></footer>
                    </article>;
                  })}
                </div>
                <button className="review-action" onClick={startReviewQuiz} disabled={busy}>按建议开始测验</button>
              </> : review ? <p className="empty">当前还没有可复习的知识点，请先提炼知识点并生成题目。</p> : <p className="empty">系统会根据正确率和近期错误安排复习。</p>}
            </section>
          </div>

          <section className="panel history-panel">
            <div className="panel-title"><div><h2>答题历史</h2><p className="panel-hint">只显示当前 PDF「{selectedSource?.title ?? "未选择资料"}」下已提交的答案</p></div><button onClick={loadHistory} disabled={!selectedSourceId || busy}>查看记录</button></div>
            {history?.length ? <div className="history-list">{history.map((item) => <article className="history-item" key={item.attempt_id}>
              <div className="history-head"><div><span>{questionTypeLabel(item.question_type)}</span><small>{item.concept_title}</small></div><span className={`status ${item.status === "correct" ? "good" : "urgent"}`}>{attemptStatusLabel(item.status)}</span></div>
              <h3>{item.prompt}</h3>
              <p className="history-answer"><strong>我的回答：</strong>{item.answer}</p>
              <p className="history-feedback"><strong>解析：</strong>{item.feedback}</p>
              <footer><small>{formatTime(item.created_at)}</small><strong>{item.score === null ? "待评分" : `得分 ${Math.round(item.score * 100)}%`}</strong></footer>
            </article>)}</div> : history ? <p className="empty">当前 PDF 还没有已提交的答题记录。开始测验并提交答案后，记录会出现在这里。</p> : <p className="empty">点击“查看记录”，查看当前 PDF 的答题历史。</p>}
          </section>

          <section className="panel quiz-panel"><div className="panel-title"><h2>本轮测验</h2><span>{questions.length ? `剩余 ${questions.length} 题` : "等待开始"}</span></div>{questions.length ? <div className="question-list">{questions.map((question) => <article key={question.question_id} className="question"><div className="question-meta"><span>{questionTypeLabel(question.question_type)}</span><small>{question.concept_title}</small></div><h3>{question.prompt}</h3>{question.options?.length ? <div className="options">{question.options.map((option) => <label key={option}><input type="radio" name={question.question_id} value={option} checked={answers[question.question_id] === option} onChange={(event) => setAnswers((current) => ({ ...current, [question.question_id]: event.target.value }))} />{option}</label>)}</div> : <textarea placeholder="用自己的话回答…" value={answers[question.question_id] ?? ""} onChange={(event) => setAnswers((current) => ({ ...current, [question.question_id]: event.target.value }))} />}<footer><small>{question.source_refs?.join(" · ")}</small><button onClick={() => perform(() => submitAnswer(question))} disabled={busy}>提交答案</button></footer></article>)}</div> : <p className="empty">点击“开始测验”获取题目。</p>}</section>
        </section>
      </section>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
