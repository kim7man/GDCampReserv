
var dsturl1 = "https://camp.xticket.kr/web/main";



window.showModalDialog = window.showModalDialog || function(url, arg, opt) {
	window.open(url, arg, opt);
};


function pad (str, max) {
  str = str.toString();
  return str.length < max ? pad("0" + str, max) : str;
}



function macrostart() {
	if (btnstart)
	{
		sessionStorage.setItem('macro', true);
		sessionStorage.setItem("targetMon", $('#targetMon').val());
		sessionStorage.setItem("targetDay", $('#targetDay').val());
		sessionStorage.setItem("areaName", $('#areaName').val());
		sessionStorage.setItem("siteNo", $('#siteNo').val());
	}


	location.reload();
}

function macrostop() {

	sessionStorage.removeItem('macro');
//	sessionStorage.removeItem('targetMon');
//	sessionStorage.removeItem('targetDay');
//	sessionStorage.removeItem('areaName');
//	sessionStorage.removeItem('siteNo');

	location.reload();
}

if (document.title == "400 Bad Request")
{
	location.reload();
}


function inject_header()
{
		var targetMon = sessionStorage.getItem("targetMon");
		var targetDay = sessionStorage.getItem("targetDay");
		var areaName = sessionStorage.getItem("areaName");
		var siteNo = sessionStorage.getItem("siteNo");


		TitleHeader = $('#header');

		if (sessionStorage.getItem('macro') == "true") {
			// 매크로 시작 이후
			TitleHeader.append('<td>월</td><td><input id="targetMon" size="3" value="' + targetMon + '"></input></td>');
			TitleHeader.append('<td>일</td><td><input id="targetDay" size="3" value="' + targetDay + '"></input></td>');
			TitleHeader.append('<td>시설</td><td><select id="areaName" style="width: 110px;"><option value="0">가족캠핑장</option><option value="1">오토캠핑장</option><option value="2">매화나무캠핑장</option></select></td>');
			TitleHeader.append('<td>사이트</td><td><input id="siteNo" size="3" value="' + siteNo + '"></input></td>');
			TitleHeader.append('<td><a href="#" id="btnstop" style="margin-left:5px;display:inline-block;vertical-align:middle;"><img src="' + chrome.runtime.getURL('images/btn_stop.png') + '"></a></td>');
			$('#areaName').val(areaName);

		} else {
			// 페이지 로딩시(매크로 시작 전)
			if(targetMon!=null)
			{
				TitleHeader.append('<td>월</td><td><input id="targetMon" size="3" value="' + targetMon + '"></input></td>');
			}
			else
			{
				TitleHeader.append('<td>월</td><td><input id="targetMon" size="3" value="4"></input></td>');
			}
			if(targetDay!=null)
			{
				TitleHeader.append('<td>일</td><td><input id="targetDay" size="3" value="' + targetDay + '"></input></td>');
			}
			else
			{
				TitleHeader.append('<td>일</td><td><input id="targetDay" size="3" value="19"></input></td>');
			}
			if(areaName!=null)
			{
				TitleHeader.append('<td>시설</td><td><select id="areaName" style="width: 110px;"><option value="0">가족캠핑장</option><option value="1">오토캠핑장</option><option value="2">매화나무캠핑장</option></select></td>');
				$('#areaName').val(areaName);
			}
			else
			{
				TitleHeader.append('<td>시설</td><td><select id="areaName" style="width: 110px;"><option value="0">가족캠핑장</option><option value="1">오토캠핑장</option><option value="2">매화나무캠핑장</option></select></td>');
				$('#areaName').val('2');
			}
			if(areaName!=null)
			{
				TitleHeader.append('<td>사이트</td><td><input id="siteNo" size="3" value="' + siteNo + '"></input></td>');
			}
			else
			{
				TitleHeader.append('<td>사이트</td><td><input id="siteNo" size="3" value="6"></input></td>');
			}
			TitleHeader.append('<td><a href="#" id="btnstart" style="margin-left:5px;display:inline-block;vertical-align:middle;"><img src="' + chrome.runtime.getURL('images/btn_start.png') + '"></a></td>');
		}

		var btnstop = document.getElementById("btnstop");
		var btnstart = document.getElementById("btnstart");

		if (btnstop) {
			btnstop.addEventListener("click", macrostop, false);
		}
		if (btnstart) {
			btnstart.addEventListener("click", macrostart, false);
		}
}


var lastTime = 0;


if (document.URL.substring(0, dsturl1.length) == dsturl1) {


//	chrome.runtime.sendMessage({type: 'playSound', data: ''});
	$(document).ready(function() {

		inject_header();

		if (sessionStorage.getItem('macro') == "true") {
			setInterval(function(){
				document.dispatchEvent(new CustomEvent('chkMacro', { detail: '' }));
			}, 100);
		}

		setTimeout(function(){
			location.reload();
		},10*60*1000);
	});
}


function recognizeDigits(canvas) {
    Tesseract.recognize(canvas, 'eng',{})
//    Tesseract.recognize(canvas, 'eng',{logger:m=>console.log(m)})
        .then(result => {
			document.dispatchEvent(new CustomEvent('captcha', { detail: result.data.text }));
        })
        .catch(err => {
            console.error(err);
        });
}


document.addEventListener('saveImage', function(e) {

	// captcha 이미지가 있는 img tag 선택
	var imgElement = $('div.ex_area img')[0];

	if (imgElement) {
		var canvas = document.createElement('canvas');
		var context = canvas.getContext('2d');
		canvas.width = imgElement.width;
		canvas.height = imgElement.height;

		// 이미지를 캔버스에 그립니다.
		context.drawImage(imgElement, 0, 0);

		// telegram 메시지 전달
		chrome.runtime.sendMessage({type: 'playSound'});
		// Tesseract를 이용 이미지에서 글자를 인식
		recognizeDigits(canvas);
	} else {
		console.error('이미지 요소를 찾을 수 없습니다.');
	}	
	
});

var script = document.createElement('script');
script.src = chrome.runtime.getURL('injectedScript.js');
document.documentElement.appendChild(script);

var script = document.createElement('script');
script.src = chrome.runtime.getURL("tesseract.min.js");
document.documentElement.appendChild(script);


