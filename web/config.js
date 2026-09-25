/* 本地与后端同源部署用空地址；静态线上网页单独指定 API。无密钥。 */
window.DSH_DEPLOYMENT = {
  local: "",
  online: "https://shuzhi-lianhai-production.up.railway.app"
};
const dshLocal = ["localhost", "127.0.0.1", "[::1]"].includes(location.hostname);
window.DSH_API_BASE = dshLocal || !location.hostname.endsWith("github.io")
  ? window.DSH_DEPLOYMENT.local : window.DSH_DEPLOYMENT.online;
