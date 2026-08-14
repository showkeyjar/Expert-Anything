let appState = { asset: null, learner: { mastery: {}, history: [], weaknesses: [] } };
let currentConcept = null;
let exerciseIndex = 0;
let explanationDepth = 0;
let selectedBaseline = "了解一些";
let selectedStyle = "例子";
let selectedConfidence = 0.7;
let readerState = {assetId: null, page: 0, totalPages: 1};

const $ = (id) => document.getElementById(id);
const escapeHtml = (value) => String(value ?? "").replace(/[&<>\"]/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[char]));
function normalizeAsset(asset) {
  const concepts = asset.concepts || [];
  return {...asset, chapters: asset.chapters || [], concepts, relations: asset.relations || [], learning_path: asset.learning_path?.length ? asset.learning_path : concepts.map((item) => item.id), exercises: asset.exercises?.length ? asset.exercises : concepts.slice(0, 5).map((item, index) => ({id:`legacy-${index}`, concept_id:item.id, prompt:`根据原文，用自己的话解释“${item.name}”。`, answer_hint:item.summary})), source_text: asset.source_text || asset.source_excerpt || "", analysis: asset.analysis || {notice:"这是旧资产的兼容视图，建议重新导入以获得完整原文。"}};
}

async function request(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "请求失败");
  return data;
}

function mastery(concept) { return appState.learner.mastery[concept.id] ?? concept.mastery ?? 0; }
function overall() { const concepts = appState.asset?.concepts || []; return concepts.length ? Math.round(concepts.reduce((sum, concept) => sum + mastery(concept), 0) / concepts.length * 100) : 0; }

function render() {
  const asset = appState.asset;
  $("emptyState").hidden = Boolean(asset);
  $("dashboard").hidden = !asset;
  $("assetList").innerHTML = (appState.assets || []).map((item) => `<div class="asset-item ${item.asset_id === asset?.asset_id ? "active" : ""}" data-id="${item.asset_id}"><div class="asset-main"><strong>${escapeHtml(item.title)}</strong><span>${item.concepts.length} 个概念 · ${item.type.toUpperCase()}</span></div><button class="delete-asset" data-delete-id="${item.asset_id}" title="删除知识资产" aria-label="删除知识资产">×</button></div>`).join("");
  $("overallMastery").textContent = `${overall()}%`;
  if (!asset) return;
  $("assetTitle").textContent = asset.title;
  $("assetMeta").textContent = `${asset.source_name} · ${asset.chapters.length} 个章节 · ${asset.concepts.length} 个概念`;
  $("conceptCount").textContent = `· ${asset.concepts.length} concepts`;
  $("sourceExcerpt").textContent = asset.source_excerpt || "暂无摘录";
  $("readerTitle").textContent = asset.title;
  $("sourceNotice").textContent = asset.analysis?.notice || "原文只读展示";
  $("readerOutline").innerHTML = asset.chapters.length ? asset.chapters.map((chapter) => `<button class="reader-outline-item">${chapter.order}. ${escapeHtml(chapter.title)}</button>`).join("") : "<span class='muted'>未识别章节</span>";
  if (readerState.assetId !== asset.asset_id) { readerState = {assetId: asset.asset_id, page: 0, totalPages: 1}; loadReaderPage(0); }
  renderSession(); renderAnalysis(); renderMap(); renderPath(); renderLearner(); renderTrajectory();
}

async function loadReaderPage(page) {
  if (!appState.asset) return;
  const result = await request(`/api/assets/${appState.asset.asset_id}/source?page=${page}`);
  readerState.page = result.page; readerState.totalPages = result.total_pages;
  $("sourceTextView").textContent = result.text || "暂无可展示的原文";
  $("readerPage").textContent = `第 ${result.page + 1} / ${result.total_pages} 页`;
  $("readerPrev").disabled = !result.has_previous; $("readerNext").disabled = !result.has_next;
}

function renderSession() {
  const session = appState.session;
  if (!session) return;
  $("tutorTitle").textContent = session.title;
  $("tutorMessage").textContent = session.message;
  $("alignmentPanel").hidden = session.phase !== "align";
  $("teachingPanel").hidden = session.phase !== "teach";
  if (session.phase !== "teach") return;
  $("lessonTitle").textContent = session.title;
  $("lessonMessage").textContent = session.message;
  $("tutorPrompt").textContent = session.prompt || "用一两句话说说，这个概念会先改变你的哪一步行动。";
  const feedback = session.feedback?.concept_id === session.concept?.id ? session.feedback : null;
  $("agentFeedback").textContent = feedback?.message || "";
  $("agentFeedback").hidden = !feedback;
  $("lessonEvidence").innerHTML = (session.source_evidence || []).map((item) => `<blockquote>${escapeHtml(item)}</blockquote>`).join("") || "<span class='muted'>暂未找到原文证据。</span>";
  $("lessonExample").textContent = session.example;
  $("knowledgePath").innerHTML = (session.knowledge_path || []).map((item, index) => `<div class="path-preview-row"><span>${index + 1}</span><div><b>${escapeHtml(item.name)}</b><i style="width:${Math.round(item.mastery * 100)}%"></i></div></div>`).join("");
  $("visualSteps").innerHTML = (session.visual_steps || []).map((step, index) => `<div class="visual-step"><span>${index + 1}</span><b>${escapeHtml(step)}</b></div>`).join("");
}

function renderAnalysis() {
  const asset = appState.asset;
  $("analysisNotice").textContent = asset.analysis?.notice || "系统已完成基础结构化提取，请结合原文核对。";
  $("chapterSummary").innerHTML = asset.chapters.map((chapter) => `<div class="chapter-row"><span class="path-number">${chapter.order}</span><div><b>${escapeHtml(chapter.title)}</b><small>原文结构节点</small></div></div>`).join("");
  $("conceptSummary").innerHTML = asset.concepts.map((concept) => `<button class="concept-summary-row" data-understand-id="${concept.id}"><span><b>${escapeHtml(concept.name)}</b><small>${concept.evidence?.length || 0} 条原文证据</small></span><span class="node-meta">${concept.evidence?.length ? "可核对" : "待核对"}</span></button>`).join("");
}

function renderMap() {
  $("conceptMap").innerHTML = appState.asset.concepts.map((concept) => `<article class="concept-node ${currentConcept?.id === concept.id ? "selected" : ""}" data-concept="${concept.id}"><strong>${escapeHtml(concept.name)}</strong><div class="progress"><i style="width:${Math.round(mastery(concept) * 100)}%"></i></div><div class="node-meta">掌握度 ${Math.round(mastery(concept) * 100)}%</div></article>`).join("");
  $("relationList").innerHTML = appState.asset.relations.length ? appState.asset.relations.map((relation) => { const from = appState.asset.concepts.find((item) => item.id === relation.from); const to = appState.asset.concepts.find((item) => item.id === relation.to); return `<div class="relation-row"><b>${escapeHtml(from?.name || relation.from)}</b><span>同句共现</span><b>${escapeHtml(to?.name || relation.to)}</b><small>${escapeHtml(relation.evidence || "有共同原文片段")}</small></div>`; }).join("") : "<div class='empty-inline'>当前原文没有足够证据建立概念关系，先从单个概念开始学习。</div>";
  if (currentConcept) renderDetail();
}

async function renderDetail() {
  const concept = currentConcept;
  explanationDepth = 0;
  const evidence = (concept.evidence || []).map((item) => `<blockquote>${escapeHtml(item)}</blockquote>`).join("");
  $("conceptDetail").innerHTML = `<p class="eyebrow">SOURCE-GROUNDED TEACHER</p><h3>${escapeHtml(concept.name)}</h3><p>系统从原文中定位到以下证据：</p><div class="evidence-list">${evidence || "<span class='muted'>暂未定位到原文证据。</span>"}</div><button class="primary-button" id="explainButton" ${evidence ? "" : "disabled"}>基于原文展开</button>`;
  $("explainButton").onclick = () => explainConcept(concept);
}

async function explainConcept(concept) {
  explanationDepth = Math.min(3, explanationDepth + 1);
  const result = await request("/api/explain", { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify({asset_id: appState.asset.asset_id, concept_id: concept.id, depth: explanationDepth}) });
  const explanation = result.explanation;
  const content = `<div class="explanation"><p class="eyebrow">${escapeHtml(explanation.label)} · ${explanation.depth}/3</p><p><b>${escapeHtml(explanation.definition)}</b></p><p>${escapeHtml(explanation.why)}</p><p>${escapeHtml(explanation.next)}</p><div class="explanation-actions"><button class="secondary-button" id="continueExplain" ${explanationDepth >= 3 ? "disabled" : ""}>${explanationDepth >= 3 ? "已展开到迁移层" : "继续深入"}</button><button class="primary-button" id="startTeaching">带着它学习</button></div></div>`;
  const previous = $("conceptDetail").querySelector(".explanation");
  if (previous) previous.outerHTML = content; else $("conceptDetail").insertAdjacentHTML("beforeend", content);
  $("continueExplain")?.addEventListener("click", () => explainConcept(concept));
  $("startTeaching")?.addEventListener("click", () => { switchTab("room"); $("roomView").scrollIntoView({behavior:"smooth", block:"start"}); });
}

function renderPath() { $("learningPath").innerHTML = appState.asset.learning_path.map((id, index) => { const concept = appState.asset.concepts.find((item) => item.id === id); if (!concept) return ""; return `<div class="path-item"><span class="path-number">${index + 1}</span><div><b>${escapeHtml(concept.name)}</b><br><small>${mastery(concept) < .6 ? "建议优先学习" : "继续巩固与迁移"}</small></div><span class="node-meta">${Math.round(mastery(concept) * 100)}%</span></div>`; }).join("") || "<div class='empty-inline'>还没有可用的学习路径。</div>"; }
function renderExercise() { if (!appState.asset.exercises.length) { $("exerciseCard").innerHTML = "<div class='empty-inline'>原文还没有形成可练习的概念。</div>"; return; } const exercise = appState.asset.exercises[exerciseIndex % appState.asset.exercises.length]; const concept = appState.asset.concepts.find((item) => item.id === exercise.concept_id) || {name:"当前概念"}; $("exerciseCard").innerHTML = `<p class="eyebrow">REVIEWER AGENT · ${exerciseIndex + 1}/${appState.asset.exercises.length}</p><h3>${escapeHtml(exercise.prompt)}</h3><p>不需要复述原文，尝试用自己的语言回答。</p><textarea class="answer" id="answer" rows="5" placeholder="写下你的理解..."></textarea><div class="exercise-actions"><span class="muted">关联概念：${escapeHtml(concept.name)}</span><div class="score-buttons"><button data-score="0.3">还不熟</button><button data-score="0.7">基本掌握</button><button data-score="1">很有把握</button></div></div>`; document.querySelectorAll("[data-score]").forEach((button) => button.onclick = () => submitAttempt(exercise, Number(button.dataset.score))); }
async function submitAttempt(exercise, score) { const result = await request("/api/attempts", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({concept_id:exercise.concept_id, score})}); appState.learner = result.learner; exerciseIndex = (exerciseIndex + 1) % appState.asset.exercises.length; render(); switchTab("practice"); }
function renderLearner() { const concepts = appState.asset.concepts; $("learnerStats").innerHTML = `<div class="stat-row"><div><b>学习增益</b><b>${overall()}%</b></div><div class="progress"><i style="width:${overall()}%"></i></div></div>` + concepts.slice(0, 5).map((concept) => `<div class="stat-row"><div><b>${escapeHtml(concept.name)}</b><span>${Math.round(mastery(concept) * 100)}%</span></div><div class="progress"><i style="width:${Math.round(mastery(concept) * 100)}%"></i></div></div>`).join(""); $("attemptHistory").innerHTML = (appState.learner.history || []).slice(0, 5).map((item) => `<div class="attempt-row"><span>${escapeHtml(item.concept_id)}</span><b>${Math.round((item.score || 0) * 100)}%</b></div>`).join("") || "<span class='muted'>还没有学习回应。</span>"; }
function renderTrajectory() { const history = appState.learner.history || []; $("trajectoryList").innerHTML = history.length ? history.map((item, index) => { const concept = appState.asset.concepts.find((entry) => entry.id === item.concept_id); return `<div class="trajectory-row"><span class="trajectory-index">${history.length - index}</span><div><b>${escapeHtml(concept?.name || item.concept_id)}</b><p>${escapeHtml(item.answer || "完成一次学习反馈")}</p></div><span class="trajectory-score">${Math.round((item.score || 0) * 100)}%</span></div>`; }).join("") : `<div class="empty-inline">还没有形成学习轨迹。先回到教学会话，完成第一个心智模型。</div>`; }
function switchTab(name) { document.querySelectorAll(".tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.tab === name)); ["room","analysis","map","source","learn","practice"].forEach((view) => { $(`${view}View`).hidden = view !== name; }); }
async function load() { const data = await request("/api/state"); data.assets = (data.assets || []).map(normalizeAsset); data.asset = data.asset ? normalizeAsset(data.asset) : null; appState = data; render(); if (appState.asset) switchTab("source"); }
function openImport() { $("importDialog").showModal(); }
function closeImport() { $("importDialog").close(); }
function goHome() { currentConcept = null; appState.asset = null; render(); switchTab("room"); window.scrollTo({ top: 0, behavior: "smooth" }); }
document.querySelectorAll(".tab").forEach((tab) => tab.onclick = () => switchTab(tab.dataset.tab));
$("homeButton").onclick = goHome;
$("newAsset").onclick = openImport; $("emptyImport").onclick = openImport; $("importTop").onclick = openImport;
$("closeImport").onclick = closeImport; $("cancelImport").onclick = closeImport;
$("readerPrev").onclick = () => loadReaderPage(readerState.page - 1);
$("readerNext").onclick = () => loadReaderPage(readerState.page + 1);
$("assetList").onclick = async (event) => { const deleteButton = event.target.closest("[data-delete-id]"); if (deleteButton) { event.stopPropagation(); const asset = (appState.assets || []).find((item) => item.asset_id === deleteButton.dataset.deleteId); if (!asset || !confirm(`确定删除“${asset.title}”吗？`)) return; const wasSelected = appState.asset?.asset_id === asset.asset_id; appState.assets = (appState.assets || []).filter((item) => item.asset_id !== asset.asset_id); if (wasSelected) { appState.asset = appState.assets[0] || null; currentConcept = null; } render(); try { await request(`/api/assets/${asset.asset_id}`, {method:"DELETE"}); await load(); } catch (error) { alert(error.message); await load(); } return; } const item = event.target.closest(".asset-item"); if (!item) return; appState.asset = (appState.assets || []).find((asset) => asset.asset_id === item.dataset.id); currentConcept = null; render(); switchTab("source"); };
$("conceptMap").onclick = (event) => { const node = event.target.closest(".concept-node"); if (!node) return; currentConcept = appState.asset.concepts.find((concept) => concept.id === node.dataset.concept); renderMap(); renderDetail(); };
document.querySelectorAll("[data-baseline]").forEach((button) => button.onclick = () => { selectedBaseline = button.dataset.baseline; document.querySelectorAll("[data-baseline]").forEach((item) => item.classList.toggle("selected-choice", item === button)); });
document.querySelectorAll("[data-style]").forEach((button) => button.onclick = () => { selectedStyle = button.dataset.style; document.querySelectorAll("[data-style]").forEach((item) => item.classList.toggle("selected-choice", item === button)); });
document.querySelectorAll("[data-confidence]").forEach((button) => button.onclick = () => { selectedConfidence = Number(button.dataset.confidence); document.querySelectorAll("[data-confidence]").forEach((item) => item.classList.toggle("selected-choice", item === button)); });
$("alignLearner").onclick = async () => { const goal = $("learnerGoal").value.trim() || "理解并能应用这份知识资产"; const result = await request("/api/session/align", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({asset_id:appState.asset.asset_id, goal, baseline:selectedBaseline, style:selectedStyle})}); appState.learner = result.learner; appState.session = result.session; renderSession(); };
$("submitTutorAnswer").onclick = async () => { const concept = appState.session?.concept; if (!concept) return; const result = await request("/api/session/respond", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({asset_id:appState.asset.asset_id, concept_id:concept.id, answer:$("tutorAnswer").value, confidence:selectedConfidence})}); appState.learner = result.learner; appState.session = result.session; $("tutorAnswer").value = ""; render(); switchTab("room"); };
$("fileInput").onchange = () => { const file = $("fileInput").files[0]; if (!file) return; $("filename").value = file.name; $("fileName").textContent = `${file.name} · ${(file.size / 1024).toFixed(1)} KB`; };
$("importForm").onsubmit = async (event) => { event.preventDefault(); const button = $("submitImport"); const file = $("fileInput").files[0]; button.disabled = true; try { const payload = {filename:$("filename").value || file?.name || "knowledge-asset.md", text:$("sourceText").value}; if (file) { const bytes = new Uint8Array(await file.arrayBuffer()); let binary = ""; bytes.forEach((byte) => binary += String.fromCharCode(byte)); payload.content_base64 = btoa(binary); payload.text = ""; } await request("/api/assets", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload)}); closeImport(); $("sourceText").value = ""; $("fileInput").value = ""; $("fileName").textContent = "未选择文件"; await load(); } catch (error) { alert(error.message); } finally { button.disabled = false; } };
load().catch((error) => { $("emptyState").querySelector("p").textContent = error.message; });
