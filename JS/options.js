var defaultBotToken = 'Set your telegram bot token';
var defaultChatId = 'Set your telegram chat id';

function save_options() {
	var botToken = document.getElementById('bot_token').value;
	var chatId = document.getElementById('chat_id').value
	//  localStorage['botToken'] = document.getElementById('bot_token').value;
	//  localStorage['chatId'] = document.getElementById('chat_id').value;  
	chrome.storage.local.set({ botToken: botToken, chatId: chatId }, function(){
		console.log('setting saved')
	});

	console.log('a');
	var url ='https://api.telegram.org/bot' + botToken + '/sendMessage?chat_id=' +chatId+ '&text=' + encodeURI('Bot connected.');

	fetch(url)
		.then(response => response.json())
		.then(data => {
			console.log('Message sent:', data);
		})
		.catch(error =>	{
			console.error('Error sending message:', error);
		});  
//  var url = 'https://api.telegram.org/bot' + botToken + '/sendMessage?chat_id=' + chatId + '&text=' + encodeURI('Bot connected.');
//		
//  var xmlhttp = new XMLHttpRequest();
//  xmlhttp.onreadystatechange=function() {
//	  if (xmlhttp.readyState==4 && xmlhttp.status==200) {
//		  var response = xmlhttp.responseText; //if you need to do something with the returned value
//      }
//  }
//  xmlhttp.open('GET', url, true);
//  xmlhttp.send();
  
//  var status = document.getElementById('status');
//    status.textContent = 'Options saved.';
//    setTimeout(function() {
//      status.textContent = '';
//    }, 750);
}

function restore_options() {
	var botToken; 
	var chatId;
	chrome.storage.local.get(['botToken', 'chatId'], function(result){
//	  botToken=result.botToken;
//	  chatId=result.chat_id;
		document.getElementById('bot_token').value = result.botToken || defaultBotToken;
		document.getElementById('chat_id').value = result.chatId || defaultChatId;	  console.log(botToken);
		console.log(chatId);
	});
//  chrome.storage.local.get(['chat_id'], function(result){chatId=result.chat_id;});
  
//	if (botToken == undefined)
//		botToken = defaultBotToken;
//
//	if (chatId == undefined)
//		chatId = defaultChatId;
//
//	document.getElementById('bot_token').value = botToken;
//	document.getElementById('chat_id').value = chatId;
}
document.addEventListener('DOMContentLoaded', restore_options);
document.getElementById('save').addEventListener('click',save_options);
