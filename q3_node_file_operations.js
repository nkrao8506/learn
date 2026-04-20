// Q3: Node.js file read, write and other operations
const fs = require("fs/promises");

async function fileOperations() {
  const filePath = "sample.txt";

  try {
    await fs.writeFile(filePath, "Line 1: Hello File\n", "utf8");
    console.log("File written.");

    await fs.appendFile(filePath, "Line 2: Appended text\n", "utf8");
    console.log("Text appended.");

    const content = await fs.readFile(filePath, "utf8");
    console.log("File content:\n" + content);

    const renamedPath = "sample-renamed.txt";
    await fs.rename(filePath, renamedPath);
    console.log("File renamed to", renamedPath);

    const stats = await fs.stat(renamedPath);
    console.log("File size:", stats.size, "bytes");

    await fs.unlink(renamedPath);
    console.log("File deleted.");
  } catch (error) {
    console.error("File operation error:", error.message);
  }
}

fileOperations();
