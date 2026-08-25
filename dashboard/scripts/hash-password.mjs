import bcrypt from "bcryptjs";
import { Writable } from "node:stream";
import { createInterface } from "node:readline/promises";

async function readPassword() {
  if (!process.stdin.isTTY) {
    const chunks = [];
    for await (const chunk of process.stdin) chunks.push(chunk);
    return Buffer.concat(chunks).toString("utf8").trim();
  }
  let muted = false;
  const output = new Writable({
    write(chunk, encoding, callback) {
      if (!muted) process.stdout.write(chunk, encoding);
      callback();
    },
  });
  const prompt = createInterface({ input: process.stdin, output, terminal: true });
  muted = true;
  const password = await prompt.question("Пароль панели: ");
  muted = false;
  process.stdout.write("\n");
  prompt.close();
  return password.trim();
}

const password = await readPassword();
if (!password) {
  process.stderr.write("Пароль не может быть пустым.\n");
  process.exit(1);
}
process.stdout.write(`${await bcrypt.hash(password, 12)}\n`);
