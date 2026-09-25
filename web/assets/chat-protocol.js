/* SSE 消费：支持网络拆包、CRLF、多行 data 与 EOF，便于独立回归测试。 */
window.DSHStream = {
  async consume(stream, onEvent) {
    const reader = stream.getReader(), decoder = new TextDecoder();
    let buffer = "";
    function emit(raw) {
      let event = "message";
      const data = [];
      for (const line of raw.split(/\r?\n/)) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
      }
      if (data.length) onEvent({ event, data: JSON.parse(data.join("\n")) });
    }
    try {
      for (;;) {
        const { value, done } = await reader.read();
        buffer += done ? decoder.decode() : decoder.decode(value, { stream: true });
        let boundary;
        while ((boundary = /\r?\n\r?\n/.exec(buffer))) {
          emit(buffer.slice(0, boundary.index));
          buffer = buffer.slice(boundary.index + boundary[0].length);
        }
        if (done) { if (buffer.trim()) emit(buffer); break; }
      }
    } finally { reader.releaseLock(); }
  }
};
