function playSound() {
	if (typeof(audio) != "undefined" && audio) {
		audio.pause();
		document.body.removeChild(audio);
		audio = null;
	}
	audio = document.createElement('audio');
	document.body.appendChild(audio);
	audio.autoplay = true;
	audio.src = chrome.extension.getURL('assets/tada.mp3');
	audio.play();
}

function sendMessageToTelegram() {
	chrome.storage.local.get(['botToken', 'chatId'], function(result){
		var botToken = result.botToken;
		var chatId = result.chatId;
		var msg = encodeURI('Check Gangdong reservation.');
		if (botToken &&	chatId)	{
			var url ='https://api.telegram.org/bot' + botToken + '/sendMessage?chat_id=' +chatId+ '&text=' + msg;

			fetch(url)
				.then(response => response.json())
				.then(data => {
					console.log('Message sent:', data);
				})
				.catch(error =>	{
					console.error('Error sending message:', error);
				});
		}
//		if (botToken && chatId) {
//			var url = 'https://api.telegram.org/bot' + botToken + '/sendMessage?chat_id=' + chatId + '&text=' + msg;
//			
//			var xmlhttp = new XMLHttpRequest();
//			xmlhttp.onreadystatechange=function() {
//				if (xmlhttp.readyState==4 && xmlhttp.status==200) {
//					var response = xmlhttp.responseText; //if you need to do something with the returned value
//				}
//			}
//			xmlhttp.open('GET', url, true);
//			xmlhttp.send();
//		}
	});
}

chrome.runtime.onMessage.addListener(function(message, sender, sendResponse) {
	console.log(message);
    if (message && message.type == 'playSound') {
//		playSound();
		sendMessageToTelegram();
        sendResponse(true);
    }
});

