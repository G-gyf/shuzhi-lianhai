const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const context = {window:{},TextDecoder};
vm.runInNewContext(fs.readFileSync('web/assets/chat-protocol.js','utf8'),context);
const consume = context.window.DSHStream.consume;
function stream(text){const bytes=new TextEncoder().encode(text);return new ReadableStream({start(c){for(const b of bytes)c.enqueue(Uint8Array.of(b));c.close();}});}
test('split UTF8, CRLF, multiline JSON and final EOF event',async()=>{
 const out=[];
 await consume(stream('event: answer_delta\r\ndata: {"text":\r\ndata: "中文"}\r\n\r\nevent: done\ndata: {}'),e=>out.push(e));
 assert.equal(out.length,2);assert.equal(out[0].data.text,'中文');assert.equal(out[1].event,'done');
});
test('malformed data rejects rather than silently reporting success',async()=>{
 const s=stream('data: broken\n\n');await assert.rejects(consume(s,()=>{}));assert.equal(s.locked,false);
});
test('consumer error releases stream reader',async()=>{
 const s=stream('data: {}\n\n');await assert.rejects(consume(s,()=>{throw Error('stopped');}));assert.equal(s.locked,false);
});
