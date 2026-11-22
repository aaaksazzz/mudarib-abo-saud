(() => {
  const API = "/api/ai-company";
  let state = {data:null, department:"all", query:"", csrf:""};
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? "").replace(/[&<>"']/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));
  const statusText = value => ({queued:"بانتظار التنفيذ",running:"قيد التنفيذ",completed:"اكتملت وراجعها المدير",needs_revision:"تحتاج مراجعة",failed:"تعذر التنفيذ"}[value] || value);
  const statusClass = value => value === "completed" ? "done" : value === "failed" ? "failed" : value === "needs_revision" ? "revision" : "";
  async function api(path, options={}) {
    const headers = {"Content-Type":"application/json", ...(options.headers||{})};
    if (options.method && options.method !== "GET") headers["X-CSRF-Token"] = state.csrf;
    const response = await fetch(API + path, {...options, headers});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || "تعذر إكمال الطلب");
    return data;
  }
  function renderStats(d) {
    $("employeeCount").textContent = d.employee_count;
    $("departmentCount").textContent = d.department_count;
    $("dailyTasks").textContent = d.daily_tasks + " / " + d.daily_task_limit;
    $("dailyTokens").textContent = Number(d.daily_tokens).toLocaleString("en-US");
    $("taskLimit").textContent = "الحد " + d.daily_task_limit + " مهمة / 24 ساعة";
    $("tokenLimit").textContent = "الحد " + Number(d.daily_token_limit).toLocaleString("en-US") + " رمز";
    $("connection").textContent = "متصل بالنظام";
    $("aiStatus").textContent = d.openai_configured ? "الذكاء الاصطناعي جاهز · " + d.model : "مفتاح OpenAI غير مضاف";
    $("aiStatus").classList.toggle("warn", !d.openai_configured);
  }
  function renderDepartments(d) {
    $("departmentFilters").innerHTML = [{id:"all",name:"كل الإدارات",count:d.employee_count}, ...d.departments].map(x =>
      '<button class="filter '+(state.department===x.id?'active':'')+'" data-dept="'+esc(x.id)+'">'+esc(x.name)+' · '+x.count+'</button>'
    ).join("");
    $("departmentFilters").querySelectorAll("button").forEach(btn => btn.addEventListener("click", () => {
      state.department = btn.dataset.dept; renderDepartments(state.data); renderEmployees(state.data);
    }));
  }
  function renderEmployees(d) {
    const q = state.query.trim().toLowerCase();
    const list = d.employees.filter(e => (state.department==="all" || e.department===state.department) &&
      (!q || [e.name,e.title,e.department_name,e.mission,e.id].join(" ").toLowerCase().includes(q)));
    $("employeeGrid").innerHTML = list.map(e =>
      '<button class="employee" data-employee="'+esc(e.id)+'"><span class="num">'+esc(e.id.toUpperCase())+'</span><b>'+esc(e.title)+'</b><small>'+esc(e.department_name)+'</small></button>'
    ).join("") || '<div class="empty">ما لقينا موظف بهذا البحث.</div>';
    $("employeeGrid").querySelectorAll("[data-employee]").forEach(btn => btn.addEventListener("click", () => showEmployee(btn.dataset.employee)));
    const select = $("taskEmployee");
    const old = select.value;
    select.innerHTML = d.employees.map(e => '<option value="'+esc(e.id)+'">'+esc(e.id.toUpperCase()+" · "+e.title)+'</option>').join("");
    if (old) select.value = old;
  }
  function renderTasks(d) {
    $("taskList").innerHTML = d.tasks.length ? d.tasks.map(t =>
      '<article class="task"><div class="task-head"><div><b>'+esc(t.title)+'</b><div class="detail-meta">'+esc(t.employee)+' · '+esc(t.employee_id.toUpperCase())+'</div></div><span class="tag '+statusClass(t.status)+'">'+statusText(t.status)+'</span></div>'+
      (t.result ? '<p>'+esc(t.result)+'</p>' : '<p>'+esc(t.brief)+'</p>')+
      (t.ceo_review ? '<p><strong>مراجعة المدير التنفيذي:</strong> '+esc(t.ceo_review)+'</p>' : '')+
      (["queued","failed","needs_revision"].includes(t.status) ? '<div class="task-actions"><button class="btn secondary" data-run="'+t.id+'">تشغيل الموظف ومراجعة المدير</button></div>' : '')+
      '</article>'
    ).join("") : '<div class="empty">ما فيه مهام مسجلة. كلف أول موظف من النموذج.</div>';
    $("taskList").querySelectorAll("[data-run]").forEach(btn => btn.addEventListener("click", () => runTask(btn.dataset.run, btn)));
  }
  function renderMeetings(d) {
    $("meetingList").innerHTML = d.meetings.length ? d.meetings.map(m =>
      '<article class="meeting"><b>'+esc(m.title)+'</b><div class="detail-meta">'+new Date(m.created_at).toLocaleString("ar-SA")+' · '+m.participants.length+' مشاركين</div><pre>'+esc(m.minutes)+'</pre>'+(m.decisions.length ? '<p><strong>القرارات والتكليفات:</strong></p><ul>'+m.decisions.map(x=>'<li>'+esc(x.decision)+(x.owner?' · '+esc(x.owner):'')+(x.due?' · '+esc(x.due):'')+'</li>').join('')+'</ul>' : '')+'</article>'
    ).join("") : '<div class="empty">لم تعقد اجتماعات بعد.</div>';
  }
  async function load() {
    $("connection").textContent = "جاري التحديث";
    try {
      const d = await api("/dashboard");
      state.data = d; state.csrf = d.csrf;
      renderStats(d); renderDepartments(d); renderEmployees(d); renderTasks(d); renderMeetings(d);
    } catch (error) {
      $("connection").textContent = "تعذر الاتصال";
      $("connection").classList.add("warn");
      $("employeeGrid").innerHTML = '<div class="empty">'+esc(error.message)+'</div>';
    }
  }
  async function showEmployee(id) {
    try {
      const d = await api("/employee/"+encodeURIComponent(id));
      const e = d.employee;
      $("detailContent").innerHTML = '<span class="eyebrow">'+esc(e.id.toUpperCase())+'</span><h2>'+esc(e.title)+'</h2><p class="detail-meta">'+esc(e.department_name)+'</p><p>'+esc(e.mission)+'</p><p><strong>مؤشر الأداء:</strong> '+esc(e.kpi)+'</p><p><strong>المهام السابقة:</strong> '+d.tasks.length+'</p>'+
        (d.tasks.map(t=>'<article class="task"><b>'+esc(t.title)+'</b><span class="tag '+statusClass(t.status)+'">'+statusText(t.status)+'</span><p>'+esc(t.result || t.ceo_review || "لم تنفذ بعد")+'</p></article>').join("") || '<p class="muted">لا توجد مهام سابقة لهذا الموظف.</p>');
      $("taskEmployee").value = id; $("detailModal").classList.remove("hidden");
    } catch (error) { alert(error.message); }
  }
  async function runTask(id, button) {
    button.disabled = true; button.textContent = "جاري التنفيذ والمراجعة…";
    try { await api("/tasks/"+id+"/run", {method:"POST",body:"{}"}); await load(); }
    catch (error) { alert(error.message); button.disabled = false; button.textContent = "إعادة المحاولة"; }
  }
  $("createTaskBtn").addEventListener("click", async () => {
    const title = $("taskTitle").value.trim(), brief = $("taskBrief").value.trim(), employee_id = $("taskEmployee").value;
    $("taskFeedback").textContent = "جاري تسجيل المهمة…";
    try {
      await api("/tasks", {method:"POST",body:JSON.stringify({title,brief,employee_id})});
      $("taskTitle").value = ""; $("taskBrief").value = "";
      $("taskFeedback").textContent = "تم تسجيل المهمة في طابور الموظف. اضغط تشغيل من سجل المهام.";
      await load();
    } catch (error) { $("taskFeedback").textContent = error.message; }
  });
  $("meetingBtn").addEventListener("click", async () => {
    const topic = prompt("وش موضوع الاجتماع؟ اكتب الهدف أو اتركه فارغاً للاجتماع اليومي.");
    if (topic === null) return;
    $("meetingBtn").disabled = true; $("meetingBtn").textContent = "الاجتماع منعقد…";
    try { await api("/meetings", {method:"POST",body:JSON.stringify({title:"اجتماع STP · "+new Date().toLocaleDateString("ar-SA"),topic})}); await load(); }
    catch (error) { alert(error.message); }
    finally { $("meetingBtn").disabled = false; $("meetingBtn").textContent = "عقد اجتماع للشركة"; }
  });
  $("refreshBtn").addEventListener("click", load);
  $("employeeSearch").addEventListener("input", e => { state.query = e.target.value; if (state.data) renderEmployees(state.data); });
  $("closeModal").addEventListener("click", () => $("detailModal").classList.add("hidden"));
  $("detailModal").addEventListener("click", e => { if (e.target.id === "detailModal") $("detailModal").classList.add("hidden"); });
  load();
})();