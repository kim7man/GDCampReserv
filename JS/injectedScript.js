// 원하는 자릿수만큼 앞에 0을 추가하는 함수
function pad (str, max) {
  str = str.toString();
  return str.length < max ? pad("0" + str, max) : str;
}

var statMacro = false;

// 원하는 달로 변경하는 함수
function changeMon()
{
	var targetMon = sessionStorage.getItem("targetMon");
	var targetDay = sessionStorage.getItem("targetDay");

	setTimeout(function() {
		// Knockout.js 와 연동된 view model을 읽어서 변수 조절
		var viewModel = ko.dataFor(document.body);
		var currentMonth = new Date().getFullYear()+pad(targetMon,2);
//		console.log(currentMonth);
		viewModel.currentMonth(currentMonth);
		selectDate(targetDay);
	}, 50); // 50ms초 후에 다시 설정
}


var captchaImgSave = false;
let timeout;
const captchaObserver = new MutationObserver((mutations) => {
	if(timeout) clearTimeout(timeout);

	timeout = setTimeout(function(){
		document.dispatchEvent(new CustomEvent('saveImage', { detail: '' }));
	},100);

	if(!captchaImgSave)
	{
		captchaImgSave = true;
	}
});

function submit()
{
	var viewModel = ko.dataFor(document.body);
	setTimeout(function(){
		viewModel.clickReservation();
		captchaObserver.observe(document.querySelector("div.chk_layer.captcha"), {
			// 변경을 감지할 요소를 지정합니다.
			subtree: true,
			// 변경의 종류를 지정합니다.
			attributes: true,
			childList: true,
			characterData: true,
		});
	}, 100);
}


// 원하는 날짜&시설&사이트를 선택하는 함수
function selectDate(targetDate) {
	var areaName = sessionStorage.getItem("areaName");
	var siteNo = sessionStorage.getItem("siteNo");


	var viewModel = ko.dataFor(document.body);

    if (viewModel && viewModel.monthCalendar && viewModel.clickBookDate) {
        var foundDate = null;

        // monthCalendar observable 배열에서 원하는 날짜를 찾습니다
        viewModel.monthCalendar().forEach(function(week) {
            week().forEach(function(day) {
                if (pad(day().dateLabel,2) == targetDate) {
                    foundDate = day;
//					console.log(foundDate());
                }
            });
        });

        if (foundDate) {
            // 날짜를 클릭합니다
//            console.log("Selected date:", foundDate().date);
            viewModel.clickBookDate(foundDate());
	
			// 일반적인 예약 시퀀스 : 시설 선택, 자리 선택 후 submit
			console.log(siteNo);
			if(siteNo > 0)
			{
				setTimeout(function(){
//					viewModel.currentProductGroupCode(areaName);
//					viewModel.currentProductGroupCode(viewModel.bookProductGroups()[2].product_group_code);
					console.log(pad(areaName*1+1,4));
					viewModel.currentProductGroupCode(pad(areaName*1+1,4)); // groupcode 0001:가족, 0002:오토, 0003:매화
//.bookProductGroups()[0].product_group_code);

					setTimeout(function(){
						viewModel.clickProduct(viewModel.products()[siteNo-1]); // 가족의 경우 이팝:0~9, 마로니에:10~20, ...
						submit();
					},200);
				},200);
			}
			// 빈자리 탐색 시퀀스 : 시설 순환, 빈자리 탐색 후 발견시 submit
			else
			{
				areaCode = 0;
				setTimeout(function(){location.reload();},3600000);
				var intTimer = setInterval(function(){
					var randDelay = Math.random()*200;
					console.log(randDelay);

					setTimeout(function(){
					areaCode++;
//					console.log(areaCode);
					viewModel.currentProductGroupCode(pad(areaCode,4)); // groupcode 0001:가족, 0002:오토, 0003:매화
					if(viewModel.products().some(function(site){if(site.select_yn=='1'&&site.status_code=='0'){siteAvailable = site; return true;}}))
					{// status code가 0이 아닌 경우, 선택 불가로 표시되어있는 자리임에도 불구하고 select_yn이 1로 남아있는 경우가 있어서 두 가지 모두 만족해야 실제 빈자리임
					// 빈자리가 존재하는 경우 해당 사이트에 대한 정보만 넘겨서 선택

						clearInterval(intTimer);
						viewModel.clickProduct(siteAvailable);
						submit();
					}
					else
					{
						if(areaCode>2)
						{
							areaCode = 0;
						}
					}
					},randDelay) // 200ms 이내의 지터 발생 => random 간격 실행과 동일한 효과
				},100); // 500ms 주기
			}
        } else {
            console.log("can't find " + targetDate);
			setTimeout(function(){
				location.reload();
			}, 100);
        }
    } else {
        console.error('뷰모델 또는 필요한 함수들을 찾을 수 없습니다.');
		setTimeout(function(){
			location.reload();
		}, 100);
    }
}

// Knockout.js가 로드된 후에 실행되도록 대기
function waitForKnockout(callback) {
    if (typeof ko !== 'undefined' && ko.dataFor(document.body)) {
        callback();
    } else {
        setTimeout(function() { waitForKnockout(callback); }, 100);
    }
}

var intTimer = null;
var count = 0;
// 뷰모델이 적용 완료되었는지 확인하는 함수
function checkViewModelReady() {
	// macro start 버튼 확인
	if (statMacro)
	{
		clearInterval(intTimer);
		var viewModel = ko.dataFor(document.body);

		if (viewModel && viewModel.currentMonth) {
//			console.log("load complete - currentMonth:", viewModel.currentMonth());
			// 원하는 달로 변경
			changeMon();
		} else {
			console.error('뷰모델 또는 currentMonth observable을 찾을 수 없습니다.');
		}
	}
	else
	{
		count++;
		if(count > 10)
		{
			clearInterval(intTimer);
		}
	}
}

// macro start 버튼 눌리면 flag 변경
document.addEventListener('chkMacro', function(e) {
	statMacro = true;
});

// 페이지 로딩 완료 시점 확인 후 함수 실행
// onload 이벤트가 DOMContentLoad이벤트보다 더 늦게 발생
// DOMContentLoad : DOM tree 완성 직후
// onload : 문서의 모든 콘텐츠(images, script, css, etc)가 로드되었을 때 발생
window.onload = function(){
	intTimer = setInterval(function(){
	    waitForKnockout(checkViewModelReady);
	}, 100);
}
//document.addEventListener('DOMContentLoaded', function() {
//    waitForKnockout(checkViewModelReady);
//});

// macro start 버튼 눌리면 flag 변경
document.addEventListener('captcha', function(e) {
	console.log(e.detail);
	var viewModel = ko.dataFor(document.body);
	viewModel.captcha(e.detail.replace(/\s+/g, ''));
	viewModel.clickReservationConfirm();
});
