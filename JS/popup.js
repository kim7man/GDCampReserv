document.getElementById('recognizeButton').addEventListener('click', function() {
    const canvas = document.getElementById('canvas');
    recognizeDigits(canvas);
});

function recognizeDigits(canvas) {
    const worker = Tesseract.createWorker({
        logger: m => console.log(m) // Optional logger to see progress
    });

    (async () => {
        await worker.load();
        await worker.loadLanguage('eng');
        await worker.initialize('eng');
        const { data: { text } } = await worker.recognize(canvas);
        document.getElementById('result').innerText = text;
        await worker.terminate();
    })();
}

document.addEventListener('popup', function(e) {
    const worker = Tesseract.createWorker({
        logger: m => console.log(m) // Optional logger to see progress
    });

    (async () => {
        await worker.load();
        await worker.loadLanguage('eng');
        await worker.initialize('eng');
        const { data: { text } } = await worker.recognize(e.canvas);
        document.getElementById('result').innerText = text;
        await worker.terminate();
    })();
});