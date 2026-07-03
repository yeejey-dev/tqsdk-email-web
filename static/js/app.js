/* =========================================================================
   期货价格监控 Web - Vue 3 应用逻辑
   ========================================================================= */
const { createApp, ref, reactive, computed, onMounted, nextTick, watch } = Vue;
const ElMessage = ElementPlus.ElMessage;

const INTERVAL_OPTIONS = [
  { label: "30秒", value: 30 },
  { label: "1分", value: 60 },
  { label: "5分", value: 300 },
  { label: "10分", value: 600 },
  { label: "15分", value: 900 },
  { label: "30分", value: 1800 },
  { label: "1时", value: 3600 },
  { label: "2时", value: 7200 },
  { label: "1天", value: 86400 },
];

const app = createApp({
  setup() {
    // -- 选项卡 --
    const activeTab = ref("config");

    // -- 折叠面板 --
    const sections = reactive({
      auth: true,
      contracts: true,
      email: false,
      schedule: false,
    });
    const toggleSection = (key) => {
      sections[key] = !sections[key];
    };

    // -- 快期认证 --
    const auth = reactive({ username: "", password: "" });

    // -- 合约 --
    const contracts = ref([]);
    const newContract = reactive({
      symbol: "",
      alias: "",
      price_high: "",
      price_low: "",
      change_pct_high: "",
      change_pct_low: "",
    });

    // -- 邮件配置 --
    const email = reactive({
      smtp_server: "",
      smtp_port: 587,
      sender_email: "",
      sender_password: "",
      receiver_emails: [],
      use_tls: true,
    });
    const receiversText = ref("");

    // -- 时间配置 --
    const schedule = reactive({
      check_interval_seconds: 300,
      send_on_interval_only: true,
      trading_hours_only: true,
      market_open_time: "09:00",
      market_close_time: "15:00",
      night_session_start: "",
      night_session_end: "",
    });
    const intervalLabel = ref("5分");
    const intervalOptions = INTERVAL_OPTIONS;

    const onIntervalChange = (label) => {
      const opt = INTERVAL_OPTIONS.find((o) => o.label === label);
      if (opt) schedule.check_interval_seconds = opt.value;
    };

    // -- 行情数据 --
    const prices = reactive({});
    const flashed = reactive({});

    // -- 日志 --
    const logs = ref([]);
    const logBody = ref(null);

    // -- 服务状态 --
    const running = ref(false);
    const starting = ref(false);
    const statusText = ref("就绪");
    const statusClass = computed(() => {
      if (running.value) return "running";
      return "idle";
    });

    // ============================================================
    // API 调用
    // ============================================================
    async function apiGet(url) {
      const res = await fetch(url);
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || "请求失败");
      }
      return res.json();
    }

    async function apiPost(url, body) {
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: body ? JSON.stringify(body) : undefined,
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || "请求失败");
      }
      return res.json();
    }

    async function apiPut(url, body) {
      const res = await fetch(url, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || "请求失败");
      }
      return res.json();
    }

    async function apiDelete(url) {
      const res = await fetch(url, { method: "DELETE" });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || "请求失败");
      }
      return res.json();
    }

    // ============================================================
    // 加载配置
    // ============================================================
    async function loadAllConfig() {
      try {
        const [authData, contractsData, emailData, scheduleData, statusData, logsData] =
          await Promise.all([
            apiGet("/api/auth"),
            apiGet("/api/contracts"),
            apiGet("/api/email"),
            apiGet("/api/schedule"),
            apiGet("/api/status"),
            apiGet("/api/logs"),
          ]);

        auth.username = authData.username || "";
        auth.password = "";

        contracts.value = contractsData;

        Object.assign(email, emailData);
        receiversText.value = (emailData.receiver_emails || []).join(",");

        Object.assign(schedule, scheduleData);
        // 同步间隔选项
        const match = INTERVAL_OPTIONS.find((o) => o.value === scheduleData.check_interval_seconds);
        intervalLabel.value = match ? match.label : "5分";
        if (schedule.night_session_start === null) schedule.night_session_start = "";
        if (schedule.night_session_end === null) schedule.night_session_end = "";

        running.value = statusData.running;
        statusText.value = statusData.message || "就绪";
        if (statusData.prices) {
          Object.keys(statusData.prices).forEach((k) => {
            prices[k] = statusData.prices[k];
          });
        }

        logs.value = logsData.lines || [];
      } catch (e) {
        ElMessage.error("加载配置失败: " + e.message);
      }
    }

    // ============================================================
    // 合约操作
    // ============================================================
    async function addContract() {
      if (!newContract.symbol.trim()) {
        ElMessage.warning("请输入合约代码");
        return;
      }
      try {
        const payload = {
          symbol: newContract.symbol.trim(),
          alias: newContract.alias.trim() || null,
          price_high: newContract.price_high ? parseFloat(newContract.price_high) : null,
          price_low: newContract.price_low ? parseFloat(newContract.price_low) : null,
          change_pct_high: newContract.change_pct_high ? parseFloat(newContract.change_pct_high) : null,
          change_pct_low: newContract.change_pct_low ? parseFloat(newContract.change_pct_low) : null,
        };
        const saved = await apiPost("/api/contracts", payload);
        contracts.value.push(saved);
        // 清空表单
        Object.keys(newContract).forEach((k) => (newContract[k] = ""));
        ElMessage.success("已添加合约: " + payload.symbol);
      } catch (e) {
        ElMessage.error(e.message);
      }
    }

    async function deleteContract(c) {
      try {
        await apiDelete("/api/contracts/" + c.id);
        contracts.value = contracts.value.filter((x) => x.id !== c.id);
        ElMessage.success("已删除: " + c.symbol);
      } catch (e) {
        ElMessage.error(e.message);
      }
    }

    // ============================================================
    // 保存配置（邮件 + 时间 + 认证）
    // ============================================================
    async function saveEmailConfig() {
      const receivers = receiversText.value
        .split(",")
        .map((r) => r.trim())
        .filter(Boolean);
      await apiPut("/api/email", { ...email, receiver_emails: receivers });
    }

    async function saveScheduleConfig() {
      const payload = { ...schedule };
      if (!payload.night_session_start) payload.night_session_start = null;
      if (!payload.night_session_end) payload.night_session_end = null;
      await apiPut("/api/schedule", payload);
    }

    async function saveAuthConfig() {
      if (auth.username && auth.password) {
        await apiPut("/api/auth", { username: auth.username, password: auth.password });
      }
    }

    // ============================================================
    // 服务控制
    // ============================================================
    async function startService() {
      // 先保存配置
      try {
        await Promise.all([saveEmailConfig(), saveScheduleConfig(), saveAuthConfig()]);
      } catch (e) {
        ElMessage.warning("部分配置保存失败: " + e.message);
      }

      if (!contracts.value.length) {
        ElMessage.error("请至少添加一个期货合约");
        return;
      }

      starting.value = true;
      try {
        const res = await apiPost("/api/start", {
          username: auth.username,
          password: auth.password,
        });
        ElMessage.success(res.message);
        running.value = true;
        statusText.value = "服务运行中";
        activeTab.value = "monitor";
      } catch (e) {
        ElMessage.error("启动失败: " + e.message);
        statusText.value = e.message;
      } finally {
        starting.value = false;
      }
    }

    async function stopService() {
      try {
        const res = await apiPost("/api/stop");
        ElMessage.success(res.message);
        // 立即更新 UI 状态，不依赖 WebSocket 推送
        running.value = false;
        statusText.value = "服务已停止";
      } catch (e) {
        ElMessage.error(e.message);
      }
    }

    // ============================================================
    // 配置导入/导出
    // ============================================================
    async function saveConfig() {
      try {
        await Promise.all([saveEmailConfig(), saveScheduleConfig()]);
        const res = await apiPost("/api/save_config");
        ElMessage.success("配置已保存到 " + res.path);
      } catch (e) {
        ElMessage.error(e.message);
      }
    }

    async function loadConfig() {
      try {
        const res = await apiPost("/api/load_config", {});
        // 刷新界面
        await loadAllConfig();
        ElMessage.success("配置已加载");
      } catch (e) {
        ElMessage.error(e.message);
      }
    }

    // ============================================================
    // 日志
    // ============================================================
    async function clearLogs() {
      try {
        await apiDelete("/api/logs");
        logs.value = [];
      } catch (e) {
        ElMessage.error(e.message);
      }
    }

    function formatLog(line) {
      // 格式: HH:MM:SS [LEVEL] message
      const match = line.match(/^(\d{2}:\d{2}:\d{2})\s*\[(\w+)\]\s*(.*)$/);
      if (match) {
        const [, time, level, msg] = match;
        const levelClass = "log-level-" + level.toLowerCase();
        return `<span class="log-time">${time}</span> <span class="${levelClass}">[${level}]</span> <span class="log-message">${escapeHtml(msg)}</span>`;
      }
      return `<span class="log-message">${escapeHtml(line)}</span>`;
    }

    function escapeHtml(text) {
      const div = document.createElement("div");
      div.textContent = text;
      return div.innerHTML;
    }

    // ============================================================
    // WebSocket
    // ============================================================
    let ws = null;
    let wsReconnectTimer = null;

    function connectWebSocket() {
      const protocol = location.protocol === "https:" ? "wss:" : "ws:";
      const wsUrl = `${protocol}//${location.host}/ws`;
      ws = new WebSocket(wsUrl);

      ws.onopen = () => {
        console.log("WebSocket 已连接");
      };

      ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        handleWsMessage(msg);
      };

      ws.onclose = () => {
        console.log("WebSocket 已断开，3秒后重连...");
        wsReconnectTimer = setTimeout(connectWebSocket, 3000);
      };

      ws.onerror = () => {
        ws.close();
      };
    }

    function handleWsMessage(msg) {
      const { event, data } = msg;
      switch (event) {
        case "price_update": {
          const symbol = data.symbol;
          prices[symbol] = data;
          // 闪烁效果
          flashed[symbol] = true;
          setTimeout(() => {
            flashed[symbol] = false;
          }, 400);
          break;
        }
        case "price_update_all": {
          Object.keys(data).forEach((k) => {
            prices[k] = data[k];
          });
          break;
        }
        case "log_update": {
          logs.value.push(data.line);
          if (logs.value.length > 500) logs.value = logs.value.slice(-500);
          nextTick(() => {
            if (logBody.value) logBody.value.scrollTop = logBody.value.scrollHeight;
          });
          break;
        }
        case "status_change": {
          running.value = data.running;
          statusText.value = data.message;
          if (!data.running && data.message && data.message.includes("失败")) {
            ElMessage.error(data.message);
          }
          break;
        }
        case "alert": {
          ElMessage.warning(`预警: ${data.symbol} - ${data.alerts.join("; ")}`);
          break;
        }
      }
    }

    // ============================================================
    // 辅助方法
    // ============================================================
    function priceCardClass(data) {
      if (data.change_pct == null) return "";
      return data.change_pct >= 0 ? "up" : "down";
    }

    function changeClass(data) {
      if (data.change_pct == null) return "neutral";
      return data.change_pct >= 0 ? "up" : "down";
    }

    function formatTime(dt) {
      if (!dt) return "--";
      // TqSdk datetime 格式: 20240101 09:30:00.000 或类似
      return String(dt).replace(/\.000/g, "").trim() || "--";
    }

    // 监听 schedule.check_interval_seconds 变化同步 intervalLabel
    watch(
      () => schedule.check_interval_seconds,
      (val) => {
        const match = INTERVAL_OPTIONS.find((o) => o.value === val);
        if (match) intervalLabel.value = match.label;
      }
    );

    // ============================================================
    // 初始化
    // ============================================================
    onMounted(() => {
      loadAllConfig();
      connectWebSocket();
    });

    return {
      // 图标
      VideoPlay: ElementPlusIconsVue.VideoPlay,
      VideoPause: ElementPlusIconsVue.VideoPause,
      Download: ElementPlusIconsVue.Download,
      Upload: ElementPlusIconsVue.Upload,
      Plus: ElementPlusIconsVue.Plus,
      Delete: ElementPlusIconsVue.Delete,

      // 状态
      activeTab,
      sections,
      toggleSection,
      auth,
      contracts,
      newContract,
      email,
      receiversText,
      schedule,
      intervalLabel,
      intervalOptions,
      onIntervalChange,
      prices,
      flashed,
      logs,
      logBody,
      running,
      starting,
      statusText,
      statusClass,

      // 方法
      addContract,
      deleteContract,
      startService,
      stopService,
      saveConfig,
      loadConfig,
      clearLogs,
      formatLog,
      priceCardClass,
      changeClass,
      formatTime,
    };
  },
});

app.use(ElementPlus);
for (const [key, comp] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, comp);
}
app.mount("#app");
