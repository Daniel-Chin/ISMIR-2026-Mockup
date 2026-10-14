$('.poster-buttons button').on('click', function() {
  var target = $(this).attr('data-target');
  $(this).siblings().removeClass('active');
  if ($(target).hasClass('show')) {
    $(target).addClass('show');
  } else {
    $('.collapse.show').removeClass('show');
  }
});

// Deep links: poster_<uid>.html#paper (or #poster, #video, #slides, #details; any case)
// opens that section, as if its button had been pressed, so a link can point at it.
// Used by the Pre-Conference Lounge. Returns false when the URL names no section on this page.
function openSectionFromHash() {
  var id = (window.location.hash || '').slice(1).toLowerCase();
  if (!/^[A-Za-z][\w-]*$/.test(id)) return false;
  var button = $('.poster-buttons button[data-target="#' + id + '"]');
  if (!button.length) return false;
  if (!$('#' + id).hasClass('show')) button.trigger('click');
  button[0].scrollIntoView({ block: 'start' });
  return true;
}

// Pressing a section button puts it in the address bar too, so the link can be copied.
$('.poster-buttons button[data-target^="#"]').on('click', function() {
  var hash = $(this).attr('data-target');
  if (window.history.replaceState && window.location.hash !== hash) window.history.replaceState(null, '', hash);
});
$(window).on('hashchange', openSectionFromHash);

$('.fullscreen-button').on('click', function() {
  fullscreen($(this).next('.fullscreen-iframe')[0])
})
// var button = document.querySelector('#fullscreen-button');
//
// button.addEventListener('click', fullscreen);
// when you are in fullscreen, ESC and F11 may not be trigger by keydown listener.
// so don't use it to detect exit fullscreen
document.addEventListener('keydown', function (e) {
  // console.log('key press' + e.keyCode);
});
// detect enter or exit fullscreen mode
document.addEventListener('webkitfullscreenchange', fullscreenChange);
document.addEventListener('mozfullscreenchange', fullscreenChange);
document.addEventListener('fullscreenchange', fullscreenChange);
document.addEventListener('MSFullscreenChange', fullscreenChange);

function fullscreen(frame) {
  // check if fullscreen mode is available
  if (document.fullscreenEnabled ||
    document.webkitFullscreenEnabled ||
    document.mozFullScreenEnabled ||
    document.msFullscreenEnabled) {

    // which element will be fullscreen
    // var iframe = document.querySelector('#fullscreen-iframe');
    // Do fullscreen
    if (frame.requestFullscreen) {
      frame.requestFullscreen();
    } else if (frame.webkitRequestFullscreen) {
      frame.webkitRequestFullscreen();
    } else if (frame.mozRequestFullScreen) {
      frame.mozRequestFullScreen();
    } else if (frame.msRequestFullscreen) {
      frame.msRequestFullscreen();
    }
  }
  else {
    document.querySelector('.error').innerHTML = 'Your browser is not supported';
  }
}

function fullscreenChange() {
  if (document.fullscreenEnabled ||
       document.webkitIsFullScreen ||
       document.mozFullScreen ||
       document.msFullscreenElement) {
    // console.log('enter fullscreen');
  }
  else {
    // console.log('exit fullscreen');
  }
  // force to reload iframe once to prevent the iframe source didn't care about trying to resize the window
  // comment this line and you will see
  var iframe = document.querySelector('iframe');
  iframe.src = iframe.src;
}


$("#fullscreen-iframe button#presentationMode").css('display', 'none !important');

$(window).ready(function() {
  // A #section in the URL wins; otherwise open the first section, as before.
  if (!openSectionFromHash()) $('.poster-buttons button').first().trigger("click");
})
